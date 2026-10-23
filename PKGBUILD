# Maintainer: InvaerLabs <your-email@example.com>
pkgname=tmusic-bin
pkgver=2.0.0
pkgrel=1
pkgdesc="A minimalist, Hyprland-optimized local music player & downloader by InvaerLabs"
arch=('x86_64')
url="https://github.com/InvaerLabs/Tmusic"
license=('MIT')
depends=('tk' 'tcl' 'ffmpeg' 'python-dbus' 'python-gobject')
provides=('tmusic')
conflicts=('tmusic')
source=("https://github.com/InvaerLabs/Tmusic/releases/download/v${pkgver}/Tmusic-v${pkgver}-arch-x86_64.tar.gz")
sha256sums=('9c8fb49521876a6d24f29333a33f7e3d7cc3e54becb04d638fdc9b0aef96bf86')

package() {
    # 1. Binary Copy to /usr/bin/tmusic
    install -Dm755 "${srcdir}/Tmusic-v${pkgver}/Tmusic" "${pkgdir}/usr/bin/tmusic"
    
    # 2. Desktop Shortcut Copy
    install -Dm644 "${srcdir}/Tmusic-v${pkgver}/tmusic.desktop" "${pkgdir}/usr/share/applications/tmusic.desktop"
    
    # 3. Icon Copy
    install -Dm644 "${srcdir}/Tmusic-v${pkgver}/assets/tmusic.png" "${pkgdir}/usr/share/pixmaps/tmusic.png"
}