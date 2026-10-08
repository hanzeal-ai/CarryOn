from pathlib import Path
q=source/'CarryOn/App/ConversationList.swift';s=q.read_text()
required = [
    "    let scroll: ConversationListScroll?",
    "            let transaction = parent.transaction",
    "                transaction?.finish(version: transactionVersion)",
    "        var applying = false",
    "                self.applying = false",
    "            guard mounted, current(), parent.scope == scope",
]
if any(anchor not in s for anchor in required):
    raise RuntimeError("Conversation list guard observation point is missing")

s=s.replace('    let scroll: ConversationListScroll?', '    let scroll: ConversationListScroll?\n    var didApply: @MainActor (Bool) -> Void = { _ in }', 1)
s=s.replace('            let transaction = parent.transaction', '            let completed = parent.didApply\n            let transaction = parent.transaction', 1)
s=s.replace('                transaction?.finish(version: transactionVersion)', '                transaction?.finish(version: transactionVersion)\n                completed(self.mounted && self.parent.scope == initialScope && current())', 1)
s=s.replace('        var applying = false','        var fixtureBeforeCompletion: (() -> Void)?\n        var fixtureBeforeScrollValidation: (() -> Void)?\n        var applying = false',1)
s=s.replace('                self.applying = false','                let fixtureHook = self.fixtureBeforeCompletion; self.fixtureBeforeCompletion = nil; fixtureHook?()\n                self.applying = false',1)
s=s.replace('            guard mounted, current(), parent.scope == scope','            let fixtureHook = fixtureBeforeScrollValidation; fixtureBeforeScrollValidation = nil; fixtureHook?()\n            guard mounted, current(), parent.scope == scope',1)
h=Path(__file__).with_name("ios_conversation_list_guards.swift").read_text()
s+=h;q.write_text(s)
f=source/'CarryOn/App/CarryOnApp.swift';t=f.read_text()
if 'let boundaryOnly = true' in t:
 if '        let result: [String: Any] = ["extraAssertions":' not in t or '"passed": (!boundaryOnly' not in t:
  raise RuntimeError("Conversation list guard result observation point is missing")
 t=t.replace('        let result: [String: Any] = ["extraAssertions":','        let listGuards = await runConversationListGuardChecks(in: keyWindow!)\n        let result: [String: Any] = ["listGuards": listGuards, "extraAssertions":',1)
 t=t.replace('"passed": (!boundaryOnly', '"passed": listGuards.count == 12 && listGuards.values.allSatisfy { $0 } && (!boundaryOnly',1)
f.write_text(t)
