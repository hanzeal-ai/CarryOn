import SwiftUI
import CarryOnCore

struct RuntimeLogView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if let failure = model.runtimeLog.storageFailure {
                        Text(failure).font(.caption).foregroundStyle(Design.orange)
                    }
                    if model.runtimeLog.entries.isEmpty {
                        BlankState(text: "暂无运行问题", symbol: "doc.text")
                    } else {
                        Text("最近 200 条").font(.caption).foregroundStyle(Design.secondary)
                        ForEach(model.runtimeLog.entries) { entry in
                            Paper {
                                VStack(alignment: .leading, spacing: 8) {
                                    HStack {
                                        Text(entry.operation).font(.subheadline.weight(.medium))
                                        Spacer()
                                        if entry.blocking { Text("需处理").font(.caption).foregroundStyle(.red) }
                                    }
                                    Text(entry.date.formatted(date: .numeric, time: .standard))
                                        .font(.caption).foregroundStyle(Design.secondary)
                                    if !entry.workspace.isEmpty {
                                        Text(entry.workspace).font(.caption).foregroundStyle(Design.secondary)
                                    }
                                    Text(entry.message).font(.subheadline).textSelection(.enabled)
                                }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }.padding(20)
            }.background(Design.background)
                .navigationTitle("运行日志").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
    }
}
