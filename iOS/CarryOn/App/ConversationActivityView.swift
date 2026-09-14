import SwiftUI
import CarryOnCore

struct ConversationActivityView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let currentThreadID: String

    var body: some View {
        NavigationStack {
            RecordListView(path: "/api/activity", key: "threads", excludedThreadID: currentThreadID) { record in
                dismiss()
                model.open(record)
            }
            .background(Design.background)
            .navigationTitle("待查看与处理").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }
    }
}
