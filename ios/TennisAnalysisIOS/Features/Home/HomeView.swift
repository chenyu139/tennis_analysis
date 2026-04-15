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
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    headerCard
                    selectedVideoCard
                    actionCard
                    exportsCard
                    statusCard
                    eventCard
                    tipsCard
                }
                .padding(16)
                .frame(maxWidth: 760, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("离线分析")
        }
        .fileImporter(
            isPresented: $isImporterPresented,
            allowedContentTypes: [.movie],
            allowsMultipleSelection: false
        ) { result in
            viewModel.handleVideoImport(result: result)
        }
        .task {
            viewModel.refreshExportedVideos()
            viewModel.prepareAutoProcessingIfRequested()
        }
    }

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("网球视频离线分析")
                .font(.system(.largeTitle, design: .rounded, weight: .bold))

            Text("在手机上导入本地比赛视频，完成球员检测、网球检测、球场关键点识别和带叠加层的视频导出。")
                .font(.subheadline)
                .foregroundStyle(.white.opacity(0.92))

            HStack(spacing: 10) {
                featureChip(title: "球员检测", systemImage: "person.2.fill")
                featureChip(title: "网球追踪", systemImage: "tennisball.fill")
                featureChip(title: "结果导出", systemImage: "square.and.arrow.down.fill")
            }
        }
        .foregroundStyle(.white)
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            LinearGradient(
                colors: [Color.blue, Color.cyan],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private var selectedVideoCard: some View {
        card(title: "当前视频", systemImage: "film.stack") {
            if let selectedURL = viewModel.selectedVideoURL {
                VStack(alignment: .leading, spacing: 6) {
                    Text(selectedURL.lastPathComponent)
                        .font(.headline)
                        .foregroundStyle(.primary)

                    Text("已复制到应用目录，可直接开始分析。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            } else {
                Text("还没有选择视频，请先导入本地 mp4 文件。")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var actionCard: some View {
        card(title: "操作", systemImage: "play.circle.fill") {
            VStack(spacing: 12) {
                Button {
                    isImporterPresented = true
                } label: {
                    Label("选择本地视频", systemImage: "square.and.arrow.down")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)

                Button {
                    viewModel.startProcessing()
                } label: {
                    Label(viewModel.isProcessing ? "正在处理中..." : "开始离线处理", systemImage: "bolt.circle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(viewModel.selectedVideoURL == nil || viewModel.isProcessing)

                if let outputURL = viewModel.outputVideoURL {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("导出文件")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(.secondary)
                        Text(outputURL.lastPathComponent)
                            .font(.subheadline)
                            .textSelection(.enabled)
                        Text("位置：文件 App -> 在我的 iPhone 上 -> TennisAnalysisIOS -> Exports")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(Color.green.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))

                    ShareLink(item: outputURL) {
                        Label("分享刚导出的视频", systemImage: "square.and.arrow.up")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                }
            }
        }
    }

    private var exportsCard: some View {
        card(title: "导出结果", systemImage: "externaldrive.badge.checkmark") {
            VStack(alignment: .leading, spacing: 12) {
                Text("如果你在“文件 App”里看不到目录，直接在这里分享导出视频即可。")
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                if viewModel.exportedVideoURLs.isEmpty {
                    Text("当前还没有可分享的导出视频。")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(viewModel.exportedVideoURLs, id: \.path) { url in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(url.lastPathComponent)
                                .font(.subheadline.weight(.semibold))
                            Text(url.path)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)

                            ShareLink(item: url) {
                                Label("分享这个视频", systemImage: "square.and.arrow.up")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.bordered)
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(.tertiarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                }

                Button {
                    viewModel.refreshExportedVideos()
                } label: {
                    Label("刷新导出列表", systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }
        }
    }

    private var statusCard: some View {
        card(title: "处理状态", systemImage: "waveform.path.ecg") {
            VStack(alignment: .leading, spacing: 12) {
                ProgressView(value: viewModel.isProcessing ? viewModel.progress : (viewModel.progress > 0 ? viewModel.progress : nil))
                    .tint(.blue)

                Text(viewModel.statusText)
                    .font(.body)
                    .foregroundStyle(.primary)

                if viewModel.isProcessing {
                    Text("分析和渲染都在本机完成，首次真机测试可能需要较长时间。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var eventCard: some View {
        card(title: "最近事件", systemImage: "text.append") {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(Array(viewModel.recentEvents.enumerated()), id: \.offset) { _, event in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "circle.fill")
                            .font(.system(size: 7))
                            .foregroundStyle(.blue)
                            .padding(.top, 5)
                        Text(event)
                            .font(.footnote)
                            .foregroundStyle(.primary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    private var tipsCard: some View {
        card(title: "使用说明", systemImage: "lightbulb") {
            VStack(alignment: .leading, spacing: 10) {
                tipRow("先通过“文件 App”或 AirDrop 把视频保存到手机。")
                tipRow("点“选择本地视频”后，系统会把视频复制进应用自己的目录。")
                tipRow("处理完成后，优先在本页“导出结果”里直接分享视频。")
            }
        }
    }

    private func card<Content: View>(title: String, systemImage: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(title, systemImage: systemImage)
                .font(.headline)
            content()
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private func featureChip(title: String, systemImage: String) -> some View {
        Label(title, systemImage: systemImage)
            .font(.footnote.weight(.semibold))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color.white.opacity(0.18))
            .clipShape(Capsule())
    }

    private func tipRow(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
            Text(text)
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }
}
