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

    /// The assistant's state from `/api/state` (idle, listening, ...), or nil if unreachable.
    func assistantState(token: String) async -> String? {
        guard let reply = await get("/api/state", token: token), reply.status == 200,
              let body = try? JSONSerialization.jsonObject(with: reply.data) as? [String: Any]
        else { return nil }
        return body["state"] as? String
    }

    private func get(_ path: String, token: String?) async -> (status: Int, data: Data)? {
        var request = URLRequest(url: URL(string: settings.origin + path)!)
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        guard let (data, response) = try? await Self.session.data(for: request),
              let http = response as? HTTPURLResponse
        else { return nil }
        return (http.statusCode, data)
    }
}
