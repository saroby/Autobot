import Testing
import SwiftData
@testable import RedApp

// The model/repository layer is INTACT in the red fixture — this logic test
// passes. Only the UI button is unwired. This is the point: a passing logic
// test does NOT prove the app works; the functional flow check must catch the
// broken UI. So RedApp's logic_tests_pass is green while functional_flows_pass
// hard-fails.
@Suite("Logic acceptances")
struct LogicAcceptanceTests {
    @Test func addItem_increasesCount() throws {
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: Item.self, configurations: config)
        let context = ModelContext(container)

        let before = try context.fetchCount(FetchDescriptor<Item>())
        context.insert(Item())
        try context.save()
        let after = try context.fetchCount(FetchDescriptor<Item>())

        #expect(after == before + 1)
    }
}
