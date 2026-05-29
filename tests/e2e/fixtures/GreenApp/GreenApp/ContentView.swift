import SwiftUI
import SwiftData

struct ContentView: View {
    @Environment(\.modelContext) private var context
    @Query private var items: [Item]

    var body: some View {
        VStack(spacing: 0) {
            // Top-level CTA, OUTSIDE the scroll list, so AXe HID taps land
            // reliably (AXe issue #42: taps inside a UIScrollView can miss).
            Button("Add") {
                addItem()
            }
            .accessibilityIdentifier("autobot.add")
            .padding()

            List(items) { _ in
                Text("Item")
                    .accessibilityIdentifier("autobot.row")
            }
        }
    }

    // GREEN variant: the button actually inserts an item, so the row count rises.
    private func addItem() {
        context.insert(Item())
    }
}
