import SwiftUI
import SwiftData

// Minimal e2e fixture (RED / deliberately broken variant). The UI is identical
// to GreenApp BUT the "Add" button is wired to nothing, so no row is ever
// inserted and the count_increased flow MUST fail. The logic/model layer is
// intact (its unit test still passes) — proving the FLOW check catches a broken
// UI wiring that a logic test alone would miss.
@main
struct RedAppApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .modelContainer(for: Item.self)
    }
}
