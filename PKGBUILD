# Maintainer: Rusty Chaffin <harrisonchaffin@gmail.com>
pkgname=focusguard
pkgver=0.1.0
pkgrel=1
pkgdesc="GUI app blocker / focus mode for Hyprland (schedules + manual sessions)"
arch=('any')
url="https://github.com/rusty/focusguard"
license=('AGPL3')
depends=('python' 'python-gobject' 'gtk4' 'libadwaita')
optdepends=('libnotify: desktop notifications when a block starts/ends'
            'systemd: user service autostart')
makedepends=('python-build' 'python-installer' 'python-wheel' 'python-setuptools')
source=()
sha256sums=()

# This PKGBUILD builds from the working directory it lives in (run
# `makepkg -si` from inside the focusguard project checkout) rather than a
# downloaded source tarball.

build() {
  cd "$startdir"
  python -m build --wheel --no-isolation --outdir "$srcdir/dist"
}

package() {
  cd "$startdir"
  python -m installer --destdir="$pkgdir" "$srcdir/dist"/*.whl

  install -Dm644 packaging/focusguard.service "$pkgdir/usr/lib/systemd/user/focusguard.service"
  install -Dm644 packaging/focusguard.desktop "$pkgdir/usr/share/applications/focusguard.desktop"
  install -Dm644 packaging/focusguard.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/focusguard.svg"
  install -Dm644 README.md "$pkgdir/usr/share/doc/focusguard/README.md"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/focusguard/LICENSE"
}
