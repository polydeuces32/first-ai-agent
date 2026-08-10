import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @State private var showImporter = false
    @State private var importedText = ""
    @State private var showDisclaimer = !UserDefaults.standard.bool(forKey: "disclaimer_seen")

    var body: some View {
        NavigationStack {
            WebContainerView(importedText: $importedText)
                .navigationTitle("EvidenceOS")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItemGroup(placement: .topBarTrailing) {
                        Button {
                            showImporter = true
                        } label: {
                            Image(systemName: "doc.text")
                        }
                        .accessibilityLabel("Import document")

                        ShareLink(item: AppConfig.tryURL) {
                            Image(systemName: "square.and.arrow.up")
                        }
                        .accessibilityLabel("Share app")
                    }
                    ToolbarItem(placement: .topBarLeading) {
                        Menu {
                            Link("Privacy", destination: AppConfig.privacyURL)
                            Link("Support", destination: AppConfig.supportURL)
                            Link("Health disclaimer", destination: AppConfig.baseURL.appendingPathComponent("health-disclaimer"))
                        } label: {
                            Image(systemName: "info.circle")
                        }
                    }
                }
                .fileImporter(
                    isPresented: $showImporter,
                    allowedContentTypes: [.plainText, .pdf, .utf8PlainText],
                    allowsMultipleSelection: false
                ) { result in
                    DocumentImporter.handle(result: result) { text in
                        importedText = text
                    }
                }
                .sheet(isPresented: $showDisclaimer) {
                    DisclaimerView {
                        UserDefaults.standard.set(true, forKey: "disclaimer_seen")
                        showDisclaimer = false
                    }
                }
        }
    }
}

struct DisclaimerView: View {
    let onAccept: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("No evidence. No answer.")
                        .font(.title.bold())
                    Text("EvidenceOS returns cited answers from your document — or refuses to guess.")
                    Text("Not medical, legal, or financial advice. Verify citations against the original source.")
                        .foregroundStyle(.secondary)
                    Link("Full health disclaimer", destination: AppConfig.baseURL.appendingPathComponent("health-disclaimer"))
                }
                .padding()
            }
            .navigationTitle("Before you start")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Continue") { onAccept() }
                }
            }
        }
    }
}

#Preview {
    ContentView()
}
