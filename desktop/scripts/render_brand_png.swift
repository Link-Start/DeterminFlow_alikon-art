import AppKit
import Foundation

guard CommandLine.arguments.count == 3 else {
    fputs("usage: render_brand_png <svg> <png>\n", stderr)
    exit(2)
}

let src = URL(fileURLWithPath: CommandLine.arguments[1])
let dst = URL(fileURLWithPath: CommandLine.arguments[2])
guard let image = NSImage(contentsOf: src) else {
    fputs("failed to load brand SVG\n", stderr)
    exit(1)
}

let width = 1024
let height = 1024
guard let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: width,
    pixelsHigh: height,
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 0
) else {
    fputs("failed to create bitmap\n", stderr)
    exit(1)
}

rep.size = NSSize(width: width, height: height)
NSGraphicsContext.saveGraphicsState()
guard let context = NSGraphicsContext(bitmapImageRep: rep) else {
    fputs("failed to create graphics context\n", stderr)
    exit(1)
}
NSGraphicsContext.current = context
NSColor.clear.setFill()
NSRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)).fill()
image.draw(
    in: NSRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)),
    from: .zero,
    operation: .sourceOver,
    fraction: 1.0,
    respectFlipped: false,
    hints: [.interpolation: NSImageInterpolation.high]
)
NSGraphicsContext.restoreGraphicsState()

guard let png = rep.representation(using: .png, properties: [:]) else {
    fputs("failed to encode PNG\n", stderr)
    exit(1)
}

do {
    try png.write(to: dst)
} catch {
    fputs("failed to write PNG: \(error)\n", stderr)
    exit(1)
}
