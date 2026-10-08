import SwiftUI
import CarryOnCore

@MainActor enum ConversationCommands {
    enum Effect { case side(String), panel(String, String), completed, continueWith(String), failed }
    static func available(_ name: String, model: AppModel, target: ConversationActionTarget) -> Bool {
        guard model.canPerform(target), ComposerCommand.names.contains(name), let command = ComposerCommand("/" + name), model.scope == target.scope, model.selectedThread?.id == target.threadID else { return false }
        let history = model.snapshot(for: target), controls = history["controls"]
        if ["review", "fork", "compact"].contains(name), history["status"]["state"].text != "idle" { return false }
        if let operation = command.operation, !controls["supportedOperations"].array.contains(.string(operation)) { return false }
        if let capability = command.capability, !model.canWrite(capability) { return false }
        return name != "plan" || controls["supportedSettings"].array.contains(.string("collaborationMode"))
    }
    static func execute(_ command: ComposerCommand, model: AppModel, target: ConversationActionTarget) async -> Effect {
        func fail(_ text: String) -> Effect {
            if model.scope == target.scope, model.selectedThread?.id == target.threadID { model.report(APIError(text)) }
            return .failed
        }
        guard available(command.name, model: model, target: target) else { return fail("当前原生连接未提供此命令：/" + command.name) }
        if ["compact", "fork", "model", "status"].contains(command.name), !command.argument.isEmpty { return fail("/" + command.name + " 不接受参数") }
        if ["plan", "side"].contains(command.name), !command.argument.isEmpty, !model.canWrite(.send) { return fail("工作区未授权发送任务") }
        switch command.name {
        case "side": return .side(command.argument)
        case "review", "fork", "status", "model": return .panel(command.name, command.argument)
        case "goal" where command.argument.isEmpty: return .panel("goal", "")
        default: break
        }
        let history = model.snapshot(for: target), controls = history["controls"]
        var action = command.name, fields: [String: JSONValue] = [:]
        if command.name == "compact", history["status"]["state"].text != "idle" || !controls["requests"].array.isEmpty || !history["queue"]["messages"].array.isEmpty { return fail("请等待会话空闲并处理排队任务与审批") }
        if command.name == "plan" {
            let settings = controls["settings"]
            guard let nativeModel = settings["model"].string ?? history["metadata"]["latestModel"].string else { return fail("原生会话尚未提供当前模型") }
            var modeSettings = settings["collaborationMode"]["settings"].object ?? [:]
            modeSettings["model"] = .string(nativeModel)
            modeSettings["reasoning_effort"] = settings["effort"] != .null ? settings["effort"] : history["metadata"]["latestReasoningEffort"]
            modeSettings["developer_instructions"] = modeSettings["developer_instructions"] ?? .null
            let mode = command.argument.isEmpty && settings["collaborationMode"]["mode"].text == "plan" ? "default" : "plan"
            action = "settings"; fields = ["settings": .object(["collaborationMode": .object(["mode": .string(mode), "settings": .object(modeSettings)])])]
        } else if command.name == "goal" {
            guard controls["goalUnknown"].bool != true else { return fail("请先核对原生目标状态") }
            action = "goal-set"; fields = ["objective": .string(command.argument), "status": .string("active")]
        }
        guard await model.perform(action, target: target, fields: fields) else { return .failed }
        return command.name == "plan" && !command.argument.isEmpty ? .continueWith(command.argument) : .completed
    }
}
