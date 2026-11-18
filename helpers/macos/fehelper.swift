// FileEngine macOS helper — on-device only (PDFKit + Vision). Read-only: never writes to the files it reads.
// usage: fehelper pdf|image|sim [maxChars] [ocrPages] [minConf] < paths.txt   → one JSON object per line on stdout
// transcribe: on-device speech to text (SpeechTranscriber). args: transcribe <locale|loc1,loc2,…> <maxMinutes> <tmpDir>
//   several locales: a 60 s sample is tried in each, the most confident one transcribes the whole file
// download < paths : ask iCloud to download files (non-blocking)
// lang list | lang install <locale> | lang release <locale>   (speech language models; Apple allows 5 reserved per app)
// sim: 64-bit difference hash + Vision image feature print (for near-duplicate photos), from a small preview
import Foundation
import PDFKit
import Vision
import AppKit
import Speech
import AVFoundation

let args = CommandLine.arguments
let mode = args.count > 1 ? args[1] : "pdf"
let maxChars = args.count > 2 ? Int(args[2]) ?? 400000 : 400000
let ocrPages = args.count > 3 ? Int(args[3]) ?? 3 : 3
let minConf = args.count > 4 ? Float(args[4]) ?? 0.35 : 0.35

func emit(_ d: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: d), let s = String(data: data, encoding: .utf8) {
        FileHandle.standardOutput.write((s + "\n").data(using: .utf8)!)
    }
}

func ocr(_ cg: CGImage) -> String {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = true
    if #available(macOS 13.0, *) { req.automaticallyDetectsLanguage = true }
    let h = VNImageRequestHandler(cgImage: cg, options: [:])
    try? h.perform([req])
    return (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

func analyse(_ cg: CGImage) -> [String: Any] {
    var out: [String: Any] = [:]
    let cls = VNClassifyImageRequest()
    let faces = VNDetectFaceRectanglesRequest()
    let h = VNImageRequestHandler(cgImage: cg, options: [:])
    try? h.perform([cls, faces])
    let labels = (cls.results ?? []).filter { $0.confidence >= minConf }.prefix(8).map { ["l": $0.identifier, "c": Double($0.confidence)] }
    out["labels"] = Array(labels)
    out["faces"] = faces.results?.count ?? 0
    out["text"] = String(ocr(cg).prefix(maxChars))
    out["w"] = cg.width; out["h"] = cg.height
    return out
}

func thumb(_ src: CGImageSource, _ px: Int) -> CGImage? {
    let o: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: px,
                              kCGImageSourceCreateThumbnailWithTransform: true, kCGImageSourceShouldCache: false]
    return CGImageSourceCreateThumbnailAtIndex(src, 0, o as CFDictionary)
}

func dhash(_ cg: CGImage) -> String {
    // 9x8 greyscale; each bit = is this pixel brighter than its right neighbour
    var px = [UInt8](repeating: 0, count: 72)
    let ctx = CGContext(data: &px, width: 9, height: 8, bitsPerComponent: 8, bytesPerRow: 9, space: CGColorSpaceCreateDeviceGray(),
                        bitmapInfo: CGImageAlphaInfo.none.rawValue)!
    ctx.interpolationQuality = .medium
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: 9, height: 8))
    var v: UInt64 = 0
    for y in 0..<8 { for x in 0..<8 { v = (v << 1) | (px[y * 9 + x] > px[y * 9 + x + 1] ? 1 : 0) } }
    return String(format: "%016llx", v)
}

func featurePrint(_ cg: CGImage) -> String? {
    let req = VNGenerateImageFeaturePrintRequest()
    let h = VNImageRequestHandler(cgImage: cg, options: [:])
    guard (try? h.perform([req])) != nil, let fp = req.results?.first as? VNFeaturePrintObservation else { return nil }
    guard fp.elementType == .float else { return nil }
    return fp.data.base64EncodedString()
}

enum FEErr: Error { case msg(String) }

func afconvert(_ src: URL, _ dst: URL) -> Bool {
    // decode anything macOS can read to plain 16 kHz mono PCM: the speech engine reads that reliably, even for long files
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/afconvert")
    p.arguments = ["-f", "WAVE", "-d", "LEI16@16000", "-c", "1", src.path, dst.path]
    p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
    do { try p.run() } catch { return false }
    p.waitUntilExit()
    return p.terminationStatus == 0 && FileManager.default.fileExists(atPath: dst.path)
}

// Tolerant decoder: keeps every readable part of a damaged sound track. Returns (frames written, stopped early?)
func readerDecode(_ url: URL, _ dst: URL) async throws -> (Int, Bool) {
    let asset = AVURLAsset(url: url)
    guard let track = try await asset.loadTracks(withMediaType: .audio).first else { throw FEErr.msg("no sound track") }
    let reader = try AVAssetReader(asset: asset)
    let settings: [String: Any] = [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1,
                                   AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false,
                                   AVLinearPCMIsNonInterleaved: false]
    let out = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
    reader.add(out)
    guard reader.startReading() else { throw FEErr.msg("cannot read sound") }
    let fmt = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
    let file = try AVAudioFile(forWriting: dst, settings: fmt.settings, commonFormat: .pcmFormatInt16, interleaved: true)
    var frames = 0
    while let sb = out.copyNextSampleBuffer() {
        guard let block = CMSampleBufferGetDataBuffer(sb) else { continue }
        let n = CMSampleBufferGetNumSamples(sb)
        if n == 0 { continue }
        guard let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: AVAudioFrameCount(n)) else { continue }
        buf.frameLength = AVAudioFrameCount(n)
        CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: n * 2, destination: buf.int16ChannelData![0])
        try file.write(from: buf)
        frames += n
    }
    return (frames, reader.status == .failed)
}

@available(macOS 26.0, *)
func audioSource(_ url: URL, _ tmp: URL, _ temps: inout [URL]) async throws -> (URL, Bool) {
    try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    let wav = tmp.appendingPathComponent(UUID().uuidString + ".wav")
    temps.append(wav)
    if afconvert(url, wav) { return (wav, false) }
    try? FileManager.default.removeItem(at: wav)
    let (frames, early) = try await readerDecode(url, wav)
    if frames < 16000 { throw FEErr.msg("cannot decode sound") }
    return (wav, early)
}

@available(macOS 26.0, *)
func runTranscriber(_ file: AVAudioFile, _ loc: Locale) async throws -> ([[Any]], Double) {
    let t = SpeechTranscriber(locale: loc, transcriptionOptions: [], reportingOptions: [], attributeOptions: [.audioTimeRange, .transcriptionConfidence])
    let analyzer = SpeechAnalyzer(modules: [t])
    let collect = Task { () -> ([[Any]], Double, Int) in
        var out: [[Any]] = []; var conf = 0.0; var n = 0
        for try await r in t.results {
            out.append([r.range.start.seconds, String(r.text.characters).trimmingCharacters(in: .whitespaces)])
            for run in r.text.runs { if let c = run.transcriptionConfidence { conf += c; n += 1 } }
        }
        return (out, conf, n)
    }
    if let last = try await analyzer.analyzeSequence(from: file) { try await analyzer.finalizeAndFinish(through: last) } else { await analyzer.cancelAndFinishNow() }
    let (segs, conf, n) = try await collect.value
    return (segs, n > 0 ? conf / Double(n) : 0)
}

func sample(_ src: URL, _ seconds: Double, _ tmp: URL) throws -> URL {
    let inF = try AVAudioFile(forReading: src)
    let fmt = inF.processingFormat
    let frames = AVAudioFrameCount(min(Double(inF.length), seconds * fmt.sampleRate))
    let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: frames)!
    try inF.read(into: buf, frameCount: frames)
    let out = tmp.appendingPathComponent(UUID().uuidString + "-sample.caf")
    let w = try AVAudioFile(forWriting: out, settings: fmt.settings, commonFormat: fmt.commonFormat, interleaved: fmt.isInterleaved)
    try w.write(from: buf)
    return out
}

@available(macOS 26.0, *)
func langCommand(_ sub: String, _ id: String) async {
    switch sub {
    case "list":
        let sup = await SpeechTranscriber.supportedLocales.map { $0.identifier(.bcp47) }.sorted()
        let inst = Set(await SpeechTranscriber.installedLocales.map { $0.identifier(.bcp47) })
        let res = await AssetInventory.reservedLocales.map { $0.identifier(.bcp47) }
        emit(["supported": sup, "installed": Array(inst).sorted(), "reserved": res, "max_reserved": AssetInventory.maximumReservedLocales])
    case "install":
        do {
            let t = SpeechTranscriber(locale: Locale(identifier: id), preset: .transcription)
            if let req = try await AssetInventory.assetInstallationRequest(supporting: [t]) {
                try await req.downloadAndInstall()
                emit(["locale": id, "installed": true, "downloaded": true])
            } else { emit(["locale": id, "installed": true, "downloaded": false]) }
        } catch { emit(["locale": id, "error": "\(error)"]) }
    case "release":
        let want = Locale(identifier: id).identifier(.bcp47)
        var ok = false
        for l in await AssetInventory.reservedLocales where l.identifier(.bcp47) == want { ok = await AssetInventory.release(reservedLocale: l) || ok }
        emit(["locale": id, "released": ok])
    default:
        emit(["error": "lang list|install <locale>|release <locale>"])
    }
}

@available(macOS 26.0, *)
func transcribe(_ path: String, _ locale: String, _ maxMin: Double, _ tmp: URL) async -> [String: Any] {
    var d: [String: Any] = ["path": path, "locale": locale]
    var temps: [URL] = []
    defer { for t in temps { try? FileManager.default.removeItem(at: t) } }
    do {
        let installed = Set(await SpeechTranscriber.installedLocales.map { $0.identifier(.bcp47) })
        let wanted = locale.split(separator: ",").map { String($0) }
        let usable = wanted.filter { installed.contains(Locale(identifier: $0).identifier(.bcp47)) }
        if usable.isEmpty { return d.merging(["error": "language model \(locale) not installed"]) { $1 } }
        let (src, partial) = try await audioSource(URL(fileURLWithPath: path), tmp, &temps)
        if partial { d["partial"] = true }
        let file = try AVAudioFile(forReading: src)
        let secs = Double(file.length) / file.processingFormat.sampleRate
        d["duration"] = secs
        if secs > maxMin * 60 { return d.merging(["error": "longer than \(Int(maxMin)) min"]) { $1 } }
        var pick = usable[0]
        if usable.count > 1 {
            // try a short sample in each language; keep the one the recogniser is most confident in
            let smp = try sample(src, 60, tmp); temps.append(smp)
            var scores: [String: Double] = [:]
            for l in usable {
                let (segs, conf) = try await runTranscriber(try AVAudioFile(forReading: smp), Locale(identifier: l))
                let words = segs.compactMap { $0[1] as? String }.joined(separator: " ").split(separator: " ").count
                scores[l] = words == 0 ? 0 : conf
            }
            d["language_scores"] = scores
            pick = scores.max { $0.value < $1.value }?.key ?? usable[0]
        }
        d["locale"] = pick
        let (segs, conf) = try await runTranscriber(file, Locale(identifier: pick))
        d["confidence"] = conf
        d["segments"] = segs
        d["text"] = segs.compactMap { $0[1] as? String }.joined(separator: " ")
    } catch FEErr.msg(let m) { d["error"] = m } catch { d["error"] = "\(error.localizedDescription)" }
    return d
}

func render(_ page: PDFPage) -> CGImage? {
    let r = page.bounds(for: .mediaBox)
    let scale: CGFloat = min(2.0, 2000.0 / max(r.width, r.height, 1))
    let img = page.thumbnail(of: NSSize(width: r.width * scale, height: r.height * scale), for: .mediaBox)
    return img.cgImage(forProposedRect: nil, context: nil, hints: nil)
}

if mode == "download" {
    // ask iCloud to bring files onto this Mac (what Finder's "Download Now" does); never reads the files
    while let line = readLine() {
        let p = line.trimmingCharacters(in: .newlines)
        if p.isEmpty { continue }
        do { try FileManager.default.startDownloadingUbiquitousItem(at: URL(fileURLWithPath: p)); emit(["path": p, "requested": true]) }
        catch { emit(["path": p, "error": "\(error.localizedDescription)"]) }
    }
    exit(0)
}

if mode == "lang" {
    if #available(macOS 26.0, *) {
        let sem = DispatchSemaphore(value: 0)
        Task { await langCommand(args.count > 2 ? args[2] : "list", args.count > 3 ? args[3] : ""); sem.signal() }
        sem.wait()
    } else { emit(["error": "needs macOS 26 or later"]) }
    exit(0)
}

while let line = readLine() {
    let path = line.trimmingCharacters(in: .newlines)
    if path.isEmpty { continue }
    let url = URL(fileURLWithPath: path)
    autoreleasepool {
        if mode == "pdf" {
            guard let doc = PDFDocument(url: url) else { emit(["path": path, "error": "unreadable"]); return }
            if doc.isLocked { emit(["path": path, "pages": doc.pageCount, "locked": true]); return }
            var text = String((doc.string ?? "").prefix(maxChars))
            var ocred = false
            if text.trimmingCharacters(in: .whitespacesAndNewlines).count < 40 && ocrPages > 0 {
                var parts: [String] = []
                for i in 0..<min(doc.pageCount, ocrPages) { if let p = doc.page(at: i), let cg = render(p) { parts.append(ocr(cg)) } }
                text = parts.joined(separator: "\n"); ocred = true
            }
            let attrs = doc.documentAttributes ?? [:]
            emit(["path": path, "pages": doc.pageCount, "text": text, "ocr": ocred,
                  "title": (attrs[PDFDocumentAttribute.titleAttribute] as? String) ?? "",
                  "author": (attrs[PDFDocumentAttribute.authorAttribute] as? String) ?? ""])
        } else if mode == "transcribe" {
            if #available(macOS 26.0, *) {
                let maxMin = args.count > 3 ? Double(args[3]) ?? 180 : 180
                let tmp = URL(fileURLWithPath: args.count > 4 ? args[4] : NSTemporaryDirectory())
                let sem = DispatchSemaphore(value: 0)
                var res: [String: Any] = [:]
                Task { res = await transcribe(path, args.count > 2 ? args[2] : "en-US", maxMin, tmp); sem.signal() }
                sem.wait()
                emit(res)
            } else { emit(["path": path, "error": "needs macOS 26 or later"]) }
        } else if mode == "sim" {
            guard let src = CGImageSourceCreateWithURL(url as CFURL, nil), let cg = thumb(src, 512) else {
                emit(["path": path, "error": "unreadable"]); return
            }
            var d: [String: Any] = ["path": path, "dhash": dhash(cg)]
            if let fp = featurePrint(cg) { d["fp"] = fp }
            if let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [String: Any] {
                d["w"] = props[kCGImagePropertyPixelWidth as String] ?? 0; d["h"] = props[kCGImagePropertyPixelHeight as String] ?? 0
                if let exif = props[kCGImagePropertyExifDictionary as String] as? [String: Any], let t = exif[kCGImagePropertyExifDateTimeOriginal as String] { d["taken"] = t }
            }
            emit(d)
        } else {
            guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
                  let cg = CGImageSourceCreateImageAtIndex(src, 0, [kCGImageSourceShouldCache: false] as CFDictionary) else {
                emit(["path": path, "error": "unreadable"]); return
            }
            var d = analyse(cg); d["path"] = path
            if let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [String: Any] {
                if let exif = props[kCGImagePropertyExifDictionary as String] as? [String: Any], let t = exif[kCGImagePropertyExifDateTimeOriginal as String] { d["taken"] = t }
                if let tiff = props[kCGImagePropertyTIFFDictionary as String] as? [String: Any], let m = tiff[kCGImagePropertyTIFFModel as String] { d["camera"] = m }
                if props[kCGImagePropertyGPSDictionary as String] != nil { d["gps"] = true }
            }
            emit(d)
        }
    }
}
