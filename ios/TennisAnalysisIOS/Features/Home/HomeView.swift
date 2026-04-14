import SwiftUI
import UniformTypeIdentifiers

struct HomeView: View {
    @StateObject private var viewModel: HomeViewModel
    @State private var isImporterPresented = false

    init(viewModel: HomeViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 20) {
                Text("Tennis Analysis")
                    .font(.largeTitle.bold())

                Text("Import a local match video, run the offline pipeline on-device, and export a rendered result aligned with the PC workflow.")
                    .foregroundStyle(.secondary)

                GroupBox("Pipeline") {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Player detection", systemImage: "person.2")
                        Label("Ball detection and interpolation", systemImage: "tennisball")
                        Label("Court keypoints and mini-court", systemImage: "rectangle.split.3x3")
                        Label("Shot speed, player speed, distance, calories", systemImage: "speedometer")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Button("Select Local Video") {
                    isImporterPresented = true
                }
                .buttonStyle(.borderedProminent)

                if let selectedURL = viewModel.selectedVideoURL {
                    Text("Selected: \(selectedURL.lastPathComponent)")
                        .font(.footnote)
                }

                Button("Start Offline Processing") {
                    viewModel.startProcessing()
                }
                .buttonStyle(.bordered)
                .disabled(viewModel.selectedVideoURL == nil || viewModel.isProcessing)

                if viewModel.isProcessing {
                    ProgressView(value: viewModel.progress)
                    Text(viewModel.statusText)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                } else {
                    Text(viewModel.statusText)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Spacer()
            }
            .padding(24)
            .navigationTitle("Offline Analysis")
        }
        .fileImporter(
            isPresented: $isImporterPresented,
            allowedContentTypes: [.movie],
            allowsMultipleSelection: false
        ) { result in
            viewModel.handleVideoImport(result: result)
        }
    }
}
