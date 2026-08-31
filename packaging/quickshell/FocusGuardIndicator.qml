// FocusGuardIndicator.qml
//
// A small Quickshell bar widget for FocusGuard (https://github.com/rustyisacat/focusguard).
// Polls `focusguardctl status --json` over a plain subprocess, so it works
// in any Quickshell config -- no FocusGuard-specific QML dependencies
// beyond this one file, and no coupling to a particular shell's theme
// system (illogical-impulse, waffle, or a from-scratch config all work).
//
// Usage: drop this file next to your other bar widgets and add
// `FocusGuardIndicator {}` inside your bar's RowLayout.
//
//   - A colored dot + blocked-app count when something is blocked.
//   - Hover for a tooltip with per-profile detail.
//   - Right-click to pause enforcement for 5 minutes / resume immediately.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

Item {
    id: root

    property int blockedCount: 0
    property bool paused: false
    property bool daemonReachable: false
    property var profileNames: []

    implicitWidth: row.implicitWidth + 16
    implicitHeight: 24

    function refresh() {
        statusProc.running = true;
    }

    Timer {
        interval: 5000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    // A short delay after a right-click action so the daemon has time to
    // apply it before we poll again, for snappier feedback than waiting
    // out the full 5s interval.
    Timer {
        id: refreshSoon
        interval: 300
        onTriggered: root.refresh()
    }

    Process {
        id: statusProc
        command: ["focusguardctl", "status", "--json"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const data = JSON.parse(text);
                    root.daemonReachable = true;
                    root.blockedCount = (data.blocked_apps || []).length;
                    root.paused = !!data.paused;
                    root.profileNames = (data.profiles || [])
                        .filter(p => p.state === "ACTIVE")
                        .map(p => p.name);
                } catch (e) {
                    root.daemonReachable = false;
                }
            }
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        onClicked: mouse => {
            if (mouse.button === Qt.RightButton) {
                Quickshell.execDetached(root.paused ? ["focusguardctl", "resume"] : ["focusguardctl", "pause", "5"]);
                refreshSoon.start();
            }
        }

        ToolTip.visible: containsMouse
        ToolTip.delay: 400
        ToolTip.text: {
            if (!root.daemonReachable)
                return "FocusGuard: daemon not running";
            if (root.paused)
                return "FocusGuard: paused\nRight-click to resume";
            if (root.blockedCount > 0)
                return "FocusGuard: blocking " + root.blockedCount + " app(s)\n(" + root.profileNames.join(", ") + ")\nRight-click to pause 5 min";
            return "FocusGuard: inactive\nRight-click to pause 5 min";
        }
    }

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: 5

        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: !root.daemonReachable ? "#888888" : root.paused ? "#f5a623" : root.blockedCount > 0 ? "#e01b24" : "#2ec27e"
        }

        Text {
            visible: root.daemonReachable
            text: root.paused ? "Paused" : root.blockedCount > 0 ? "🛡 " + root.blockedCount : "FocusGuard"
            color: "#cfd6f5"
            font.pixelSize: 12
        }
    }
}
