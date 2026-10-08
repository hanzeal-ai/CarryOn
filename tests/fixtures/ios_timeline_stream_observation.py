from pathlib import Path
f=source/'CarryOn/App/CarryOnApp.swift'
s=f.read_text().replace('@ObservationIgnored var timings:', '@ObservationIgnored var streamRequests: [[String: Any]] = []\n    @ObservationIgnored var streamObserved: [[String: Any]] = []\n    @ObservationIgnored var timings:',1)
s=s.replace('.task { await fixture.run() }', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.streamObserved"))) { note in if var value = note.object as? [String: Any] { value["time"] = CACurrentMediaTime() - fixture.start; fixture.streamObserved.append(value) } }\n                .task { await fixture.run() }',1)
s=s.replace('rows[rows.count - 1] = entry("a3",', 'streamRequests.append(["time": CACurrentMediaTime() - start, "sequence": n])\n            rows[rows.count - 1] = entry("a3",',1)
s=s.replace('.joined()); sync()', '.joined()); streamRequests[streamRequests.count - 1]["utf16Length"] = rows[rows.count - 1]["text"].text.utf16.count; streamRequests[streamRequests.count - 1]["text"] = rows[rows.count - 1]["text"].text; sync()',1)
s=s.replace('let result: [String: Any] =', 'let streamBodiesObserved = streamRequests.count == 5 && streamRequests.allSatisfy { request in guard let length = request["utf16Length"] as? Int, let text = request["text"] as? String else { return false }; return streamObserved.contains { ($0["utf16Length"] as? Int) == length && ($0["text"] as? String) == text } }\n        let result: [String: Any] =',1)
s=s.replace('"passed":', '"streamBodiesObserved": streamBodiesObserved, "passed": streamBodiesObserved &&',1)
s=s.replace('"measurement": "frameIntervals",', '"measurement": "frameIntervals", "streamRequests": streamRequests, "streamObserved": streamObserved,',1)
f.write_text(s)
p=source/'CarryOn/App/ConversationView.swift';s=p.read_text()
anchor='        let kind = item["type"].text'
s=s.replace(anchor, '        let _ = { if item.stableID == "a3", item["text"].text.hasPrefix("回复段落") { NotificationCenter.default.post(name: .init("fixture.streamObserved"), object: ["utf16Length": item["text"].text.utf16.count, "text": item["text"].text]) } }()\n'+anchor,1)
p.write_text(s)
