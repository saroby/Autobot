import Foundation
import SwiftData

@Model
final class Item {
    var createdAt: Date
    init(createdAt: Date = .now) {
        self.createdAt = createdAt
    }
}
