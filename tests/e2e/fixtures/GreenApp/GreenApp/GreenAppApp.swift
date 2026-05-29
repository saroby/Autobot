import SwiftUI
import SwiftData

// Minimal e2e fixture (GREEN / working variant). Tapping the top-level "Add"
// button inserts an Item; each Item renders a row carrying autobot.row, so the
// count_increased postcondition (element count of autobot.row goes up) holds.
@main
struct GreenAppApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .modelContainer(for: Item.self)
    }
}
