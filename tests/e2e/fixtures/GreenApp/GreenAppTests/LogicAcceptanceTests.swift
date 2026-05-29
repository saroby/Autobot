import Testing
import SwiftData
@testable import GreenApp

// P0 logic acceptance "addItem_increasesCount": inserting an Item into an
// in-memory SwiftData container raises the stored count by one. Named exactly
// after the feature-spec acceptance id so check_logic_tests_pass's completeness
// sub-check matches it.
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
