import Foundation

/// Talks to the daemon's HTTP API on 127.0.0.1 with the token from `$VISION_HOME/token`.
struct DaemonClient: Sendable {
    let settings: Settings

    private static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 2
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }()

    func readToken() -> String? {
        guard let text = try? String(contentsOf: settings.token, encoding: .utf8) else { return nil }
        let token = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }

    /// The HTTP status of `GET path`, or nil when nothing answers on the port.
    func status(_ path: String, token: String?) async -> Int? {
        await get(path, token: token)?.status
    }

    /// The assistant's state from `/api/state` (idle, listening, ...) and how voice listens,
    /// or nil if unreachable.
    func assistantState(token: String) async -> (state: String, listen: Listen?)? {
        guard let reply = await get("/api/state", token: token), reply.status == 200,
              let body = try? JSONSerialization.jsonObject(with: reply.data) as? [String: Any],
              let state = body["state"] as? String
        else { return nil }
        return (state, Listen(body["listen"]))
    }

    /// Asks the daemon to listen in `mode` (`PATCH /api/settings`); nil when it took it,
    /// else the daemon's reason in its own words.
    func setListen(_ mode: String, token: String) async -> String? {
        let body = try? JSONSerialization.data(withJSONObject: ["voice": ["listen": mode]])
        guard let reply = await send("PATCH", "/api/settings", token: token, body: body) else {
            return "\(settings.name) did not answer."
        }
        if reply.status == 200 { return nil }
        let detail = (try? JSONSerialization.jsonObject(with: reply.data) as? [String: Any])?["detail"]
        let errors = (detail as? [String: Any])?["errors"] as? [[String: Any]]
        return errors?.first?["message"] as? String ?? "The change was refused (HTTP \(reply.status))."
    }

    private func get(_ path: String, token: String?) async -> (status: Int, data: Data)? {
        await send("GET", path, token: token, body: nil)
    }

    private func send(_ method: String, _ path: String, token: String?, body: Data?) async -> (status: Int, data: Data)? {
        var request = URLRequest(url: URL(string: settings.origin + path)!)
        request.httpMethod = method
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        guard let (data, response) = try? await Self.session.data(for: request),
              let http = response as? HTTPURLResponse
        else { return nil }
        return (http.statusCode, data)
    }
}
