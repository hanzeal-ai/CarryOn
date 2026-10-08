import SwiftUI
import UIKit

struct ConversationListRow {
    let id: String
    let configuration: AnyHashable?
    let content: AnyView
}

@MainActor struct ConversationList: UIViewRepresentable {
    let rows: [ConversationListRow]
    let scope: String
    let isCurrent: @MainActor () -> Bool
    let mayFollowLatest: @MainActor () -> Bool
    let onOffset: @MainActor (CGFloat) -> Void
    let olderBoundaryID: String?
    let canLoadEarlier: Bool
    let loadEarlier: @MainActor () async -> Void
    let transaction: ConversationListTransaction?
    let scroll: ConversationListScroll?

    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIView(context: Context) -> UITableView {
        let table = UITableView(frame: .zero, style: .plain)
        table.separatorStyle = .none
        table.backgroundColor = .clear
        table.showsVerticalScrollIndicator = false
        table.scrollsToTop = false
        table.keyboardDismissMode = .interactive
        table.transform = CGAffineTransform(rotationAngle: .pi)
        table.register(UITableViewCell.self, forCellReuseIdentifier: "conversation-list-row")
        table.delegate = context.coordinator
        table.estimatedRowHeight = 60
        table.rowHeight = UITableView.automaticDimension
        context.coordinator.attach(table)
        return table
    }
    func updateUIView(_ table: UITableView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.update()
    }
    static func dismantleUIView(_ table: UITableView, coordinator: Coordinator) {
        coordinator.mounted = false
        table.delegate = nil
        coordinator.olderTask?.cancel(); coordinator.olderTask = nil; coordinator.olderToken = nil
        coordinator.parent.transaction?.finish()
    }

    @MainActor final class Coordinator: NSObject, UITableViewDelegate {
        var parent: ConversationList
        weak var table: UITableView?
        var source: UITableViewDiffableDataSource<Int, String>?
        var values: [String: ConversationListRow] = [:]
        var applying = false
        var pending = false
        var mounted = true
        var panIntent: UInt64 = 0
        var scope = ""
        var lastScroll: UUID?
        var olderTask: Task<Void, Never>?
        var olderToken: UUID?
        var lastOlderBoundary: String?
        init(_ parent: ConversationList) { self.parent = parent }
        func attach(_ table: UITableView) {
            self.table = table
            source = UITableViewDiffableDataSource<Int, String>(tableView: table) { [weak self] table, index, id in
                let cell = table.dequeueReusableCell(withIdentifier: "conversation-list-row", for: index)
                guard let self, self.mounted, self.scope == self.parent.scope, self.parent.isCurrent(), let row = self.values[id] else { cell.contentConfiguration = nil; return cell }
                cell.selectionStyle = .none
                cell.backgroundColor = .clear
                cell.contentConfiguration = UIHostingConfiguration {
                    row.content.rotationEffect(.degrees(180))
                }.minSize(width: 0, height: 0).margins(.all, 0)
                return cell
            }
        }
        func update() {
            guard mounted, let table, let source, parent.isCurrent() else { parent.transaction?.finish(); return }
            if scope != parent.scope {
                olderTask?.cancel(); olderTask = nil; olderToken = nil; lastOlderBoundary = nil
            }
            if applying { pending = true; return }
            let identifiers = parent.rows.reversed().map(\.id)
            guard Set(identifiers).count == identifiers.count else { parent.transaction?.finish(); return }
            let oldIDs = source.snapshot().itemIdentifiers
            let next = Dictionary(uniqueKeysWithValues: parent.rows.map { ($0.id, $0) })
            let changed = identifiers.filter { id in
                guard let old = values[id], let current = next[id] else { return false }
                return old.configuration != current.configuration
            }
            guard identifiers != oldIDs || !changed.isEmpty || scope != parent.scope else { applyScroll(); checkPagination(); parent.transaction?.finish(); return }
            let initialScope = parent.scope
            let changedScope = scope != initialScope
            let current = parent.isCurrent
            let transaction = parent.transaction
            let transactionVersion = transaction?.version ?? 0
            let intent = panIntent
            let follow = !changedScope && table.contentOffset.y <= 0.5 && !table.isDragging && !table.isDecelerating && parent.mayFollowLatest()
            let preserved = changedScope ? nil : table.indexPathsForVisibleRows?.first.flatMap { index -> (String, CGFloat, CGFloat)? in
                guard let id = source.itemIdentifier(for: index) else { return nil }
                return (id, table.rectForRow(at: index).minY, table.contentOffset.y)
            }
            // No detached diff or await between current-state validation and application.
            guard parent.isCurrent() else { parent.transaction?.finish(); return }
            values = next; scope = initialScope; applying = true
            var snapshot = NSDiffableDataSourceSnapshot<Int, String>()
            snapshot.appendSections([0]); snapshot.appendItems(identifiers)
            if changedScope {
                let retained = Set(oldIDs)
                snapshot.reconfigureItems(identifiers.filter { retained.contains($0) })
            } else { snapshot.reconfigureItems(changed) }
            source.apply(snapshot, animatingDifferences: false) { [weak self] in
                guard let self else { return }
                self.applying = false
                if self.mounted, self.scope == initialScope, self.parent.scope == initialScope, current(),
                   let table = self.table, self.panIntent == intent, !table.isDragging, !table.isDecelerating,
                   self.parent.mayFollowLatest() {
                    table.layoutIfNeeded()
                    if self.parent.scope == initialScope, current(), self.panIntent == intent, !table.isDragging, !table.isDecelerating, self.parent.mayFollowLatest() {
                    if follow { table.setContentOffset(.zero, animated: false) }
                    else if let preserved, let index = self.source?.indexPath(for: preserved.0) {
                        let offset = preserved.2 + table.rectForRow(at: index).minY - preserved.1
                        table.setContentOffset(CGPoint(x: 0, y: offset), animated: false)
                    }
                }
                    }
                self.applyScroll()
                transaction?.finish(version: transactionVersion)
                if self.pending { self.pending = false; self.update() }
                else { self.checkPagination() }
            }
        }
        func applyScroll() {
            guard mounted, scope == parent.scope, parent.isCurrent(), let table, let request = parent.scroll, request.id != lastScroll else { return }
            if let id = request.messageID, source?.indexPath(for: id) == nil { return }
            if request.messageID == nil {
                guard let boundary = parent.olderBoundaryID, source?.indexPath(for: boundary) != nil else { return }
            }
            let current = parent.isCurrent, scope = parent.scope
            let intent = panIntent
            table.layoutIfNeeded()
            guard mounted, current(), parent.scope == scope, parent.scroll?.id == request.id, panIntent == intent else { return }
            panIntent &+= 1
            if let id = request.messageID, let index = source?.indexPath(for: id), table.indexPathsForVisibleRows?.contains(index) != true {
                table.scrollToRow(at: index, at: request.position, animated: false)
                table.layoutIfNeeded()
                guard mounted, current(), parent.scope == scope, parent.scroll?.id == request.id, panIntent == intent &+ 1 else { return }
            }
            var target = request.offset
            if let id = request.messageID, let index = source?.indexPath(for: id) {
                let rect = table.rectForRow(at: index)
                target += request.position == .middle ? rect.midY - table.bounds.height / 2 : request.position == .bottom ? rect.minY : rect.maxY - table.bounds.height
            }
            let maximum = max(0, table.contentSize.height - table.bounds.height + table.adjustedContentInset.bottom)
            table.setContentOffset(CGPoint(x: 0, y: max(-table.adjustedContentInset.top, min(target, maximum))), animated: false)
            lastScroll = request.id
        }
        func checkPagination() {
            guard mounted, !applying, scope == parent.scope, parent.isCurrent(), let table, let boundary = parent.olderBoundaryID else { return }
            let visible = table.indexPathsForVisibleRows?.contains { source?.itemIdentifier(for: $0) == boundary } == true
            if !visible { lastOlderBoundary = nil; return }
            guard parent.canLoadEarlier, olderTask == nil, lastOlderBoundary != boundary else { return }
            lastOlderBoundary = boundary
            let scope = parent.scope, current = parent.isCurrent, load = parent.loadEarlier
            let token = UUID(); olderToken = token
            olderTask = Task { [weak self] in
                guard let self else { return }
                guard self.olderToken == token else { return }
                if self.mounted, current(), self.parent.scope == scope { await load() }
                guard self.olderToken == token else { return }
                self.olderTask = nil; self.olderToken = nil
                if self.mounted, current(), self.parent.scope == scope { self.checkPagination() }
            }
        }

        func tableView(_ tableView: UITableView, willDisplay cell: UITableViewCell, forRowAt indexPath: IndexPath) {
            if !applying { checkPagination() }
        }
        func scrollViewWillBeginDragging(_ scrollView: UIScrollView) { panIntent &+= 1 }
        func scrollViewDidScroll(_ scrollView: UIScrollView) {
            guard mounted, scope == parent.scope, parent.isCurrent() else { return }
            parent.onOffset(scrollView.contentOffset.y)
            if !applying { checkPagination() }
        }
    }
}

@MainActor final class ConversationListTransaction {
    var pending: [UInt64: CheckedContinuation<Void, Never>] = [:]
    var version: UInt64 = 0
    var appliedVersion: UInt64 = 0
    func callAsFunction(_ updates: @MainActor () -> Void) async {
        version &+= 1
        let target = version
        updates()
        await withCheckedContinuation { continuation in
            if appliedVersion >= target { continuation.resume() }
            else { pending[target] = continuation }
        }
    }
    func finish(version target: UInt64? = nil) {
        appliedVersion = max(appliedVersion, target ?? version)
        for key in pending.keys.filter({ $0 <= appliedVersion }) { pending.removeValue(forKey: key)?.resume() }
    }
}
struct ConversationListScroll: Equatable {
    let id = UUID()
    var messageID: String?
    var position: UITableView.ScrollPosition = .middle
    var offset: CGFloat = 0
    init(messageID: String, position: UITableView.ScrollPosition, offset: CGFloat = 0) {
        self.messageID = messageID; self.position = position; self.offset = offset
    }
    init(offset: CGFloat) { self.offset = offset }
}

@MainActor struct ConversationListLiveContent: View {
    let build: () -> AnyView
    var body: some View { build() }
}

struct ConversationListOptionalMenu: ViewModifier {
    let enabled: Bool
    let actions: [(String, () -> Void)]
    func body(content: Content) -> some View {
        if enabled {
            content.contextMenu {
                ForEach(actions.indices, id: \.self) { index in Button(actions[index].0, action: actions[index].1) }
            }
        } else { content }
    }
}
