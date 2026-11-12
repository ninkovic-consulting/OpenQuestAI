import AppKit
import WebKit

/// The house page in a WKWebView, kept to the daemon's own origin.
///
/// The token reaches the page the way `vision ui` hands it over: a user script
/// defines `window.pywebview.api.token()`, which `web/src/net/token.ts` calls,
/// so the token never appears in a URL. The rest of that API is in `Bridge`.
@MainActor
final class PageView: NSObject, WKNavigationDelegate, WKUIDelegate {
    let webView: WKWebView
    private let settings: Settings
    var onLoadFailed: (String) -> Void = { _ in }

    init(settings: Settings, supervisor: Supervisor, token: String) {
        self.settings = settings
        let config = WKWebViewConfiguration()
        let bridge = Bridge(settings: settings, supervisor: supervisor)
        config.userContentController.addScriptMessageHandler(
            bridge, contentWorld: .page, name: Bridge.handlerName
        )
        config.userContentController.addUserScript(
            WKUserScript(
                source: Bridge.script(token: token, origin: settings.origin),
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
        config.mediaTypesRequiringUserActionForPlayback = []
        webView = KeyWebView(frame: .zero, configuration: config)
        webView.setValue(false, forKey: "drawsBackground")
        bridge.webView = webView
        super.init()
        webView.navigationDelegate = self
        webView.uiDelegate = self
    }

    func load() {
        webView.load(URLRequest(url: settings.page))
    }

    /// Evaluates `script` in the page and returns its string result.
    func evaluate(_ script: String) async -> String? {
        try? await webView.evaluateJavaScript(script) as? String
    }

    private func isOwnPage(_ url: URL?) -> Bool {
        guard let url, let scheme = url.scheme, let host = url.host else { return false }
        return "\(scheme)://\(host):\(url.port ?? 80)" == settings.origin
    }

    // MARK: WKNavigationDelegate

    func webView(
        _ webView: WKWebView,
        decidePolicyFor action: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        if isOwnPage(action.request.url) || action.request.url?.scheme == "about" {
            decisionHandler(.allow)
            return
        }
        if let url = action.request.url, ["http", "https"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        onLoadFailed(error.localizedDescription)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        load()
    }

    // MARK: WKUIDelegate

    /// Links that ask for a new window open in the default browser instead.
    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for action: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = action.request.url, !isOwnPage(url) { NSWorkspace.shared.open(url) }
        return nil
    }
}

/// Takes keyboard focus as soon as it is in a window, so `/`, Space and Escape reach the page.
private final class KeyWebView: WKWebView {
    override var acceptsFirstResponder: Bool { true }
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        window?.makeFirstResponder(self)
    }
}
