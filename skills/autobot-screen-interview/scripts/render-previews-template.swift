import SwiftUI
import AppKit

// autobot-screen-interview 프리뷰 렌더 하네스 템플릿.
//
// 사용법 (대상 프로젝트에 designs/render-previews.swift 로 복사 후):
//   1) cases 배열을 화면 spec 의 R4 상태 매트릭스에 맞게 채운다 (상태당 1개 + 다크 1개)
//   2) 뷰 파일과 함께 컴파일·실행:
//      swiftc -parse-as-library Views/<ScreenName>View.swift designs/render-previews.swift \
//        -o /tmp/render-previews && /tmp/render-previews
//   3) designs/previews/*.png 생성 확인 → Read 로 대화에 표시 + open 으로 사용자에게 열기
//
// NSHostingView 스냅샷을 쓰는 이유: ImageRenderer 는 ScrollView/Lazy 컨테이너를
// 백지로 렌더한다 (검증됨). 뷰 쪽도 presentation-only 에서는 LazyVStack 대신 VStack.
@main
struct PreviewRenderer {
    static func main() throws {
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.prohibited)

        let out = URL(fileURLWithPath: "designs/previews")
        try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        let size = CGSize(width: 393, height: 852) // iPhone 세로 뷰포트

        // <-- 여기를 R4 상태 매트릭스로 교체
        let cases: [(name: String, view: AnyView, dark: Bool)] = [
            // ("01-default", AnyView(MyScreenView()), false),
            // ("02-empty", AnyView(MyScreenView(state: .empty)), false),
            // ("99-dark", AnyView(MyScreenView()), true),
        ]

        for c in cases {
            let host = NSHostingView(rootView: c.view.frame(width: size.width, height: size.height).background(.background))
            host.frame = CGRect(origin: .zero, size: size)
            host.appearance = NSAppearance(named: c.dark ? .darkAqua : .aqua)

            let window = NSWindow(contentRect: host.frame, styleMask: [.borderless],
                                  backing: .buffered, defer: false)
            window.contentView = host
            host.layoutSubtreeIfNeeded()
            RunLoop.main.run(until: Date().addingTimeInterval(0.2)) // 비동기 레이아웃 정착

            guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else {
                print("FAIL: \(c.name) (no bitmap rep)")
                continue
            }
            host.cacheDisplay(in: host.bounds, to: rep)
            guard let png = rep.representation(using: .png, properties: [:]) else {
                print("FAIL: \(c.name) (no png)")
                continue
            }
            try png.write(to: out.appendingPathComponent("\(c.name).png"))
            print("OK: \(c.name).png")
        }
    }
}
