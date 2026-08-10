import Foundation

enum AppConfig {
    /// Production URL for the hosted EvidenceOS demo.
    /// Override in Xcode build settings: EVIDENCEOS_BASE_URL
    static var baseURL: URL {
        let raw = Bundle.main.object(forInfoDictionaryKey: "EVIDENCEOS_BASE_URL") as? String
            ?? "https://evidenceos.app"
        return URL(string: raw) ?? URL(string: "https://evidenceos.app")!
    }

    static var tryURL: URL { baseURL.appendingPathComponent("try") }
    static var privacyURL: URL { baseURL.appendingPathComponent("privacy") }
    static var supportURL: URL { baseURL.appendingPathComponent("support") }
    static var supportEmail: String { "support@evidenceos.app" }
}
