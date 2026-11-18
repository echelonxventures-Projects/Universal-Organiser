// Put items in the Trash the way Finder does (works for iCloud-only items without downloading them).
// One path per line on stdin; one JSON line per item on stdout: {"path":..., "trash":...} or {"path":..., "error":...}
import Foundation
setvbuf(stdout, nil, _IOLBF, 0)
while let line = readLine() {
    if line.isEmpty { continue }
    var out: NSURL?
    var d: [String: Any] = ["path": line]
    do {
        try FileManager.default.trashItem(at: URL(fileURLWithPath: line), resultingItemURL: &out)
        d["trash"] = (out as URL?)?.path ?? ""
    } catch { d["error"] = error.localizedDescription }
    let j = try! JSONSerialization.data(withJSONObject: d)
    print(String(data: j, encoding: .utf8)!)
}
