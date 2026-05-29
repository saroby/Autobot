import SwiftUI
import SwiftData

struct ContentView: View {
    @Environment(\.modelContext) private var context
    @Query private var items: [Item]

    var body: some View {
        VStack(spacing: 0) {
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

    // RED variant: deliberately broken — the button does NOT insert anything,
    // so tapping autobot.add never raises the autobot.row count. The
    // count_increased flow assertion must therefore FAIL.
    private func addItem() {
        // no-op (bug)
    }
}
