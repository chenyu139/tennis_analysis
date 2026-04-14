import SwiftUI

@main
struct TennisAnalysisIOSApp: App {
    var body: some Scene {
        WindowGroup {
            HomeView(viewModel: HomeViewModel())
        }
    }
}
