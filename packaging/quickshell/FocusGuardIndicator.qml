// FocusGuardIndicator.qml
//
// A small Quickshell bar widget for FocusGuard (https://github.com/rustyisacat/focusguard).
// Polls `focusguardctl status --json` over a plain subprocess, so it works
// in any Quickshell config -- no FocusGuard-specific QML dependencies
// beyond this one file, and no coupling to a particular shell's theme
// system (illogical-impulse, waffle, or a from-scratch config all work).
// Does depend on Quickshell's Hyprland, Mpris, Wayland, and Io modules
// (all core Quickshell modules, not ii-specific) for the reactive Vigi
// below.
//
// Usage: drop this file next to your other bar widgets and add
// `FocusGuardIndicator {}` inside your bar's RowLayout.
//
//   - A tiny pixel-art Vigi + a colored status dot + blocked-app count.
//   - Vigi reacts to what's actually happening on screen, independent of
//     whether FocusGuard is blocking anything:
//       * grooves faster when music is playing (any MPRIS player)
//       * flashes amber and gives a little shake when a "distracting" app
//         (see distractingApps below) is the focused window
//       * gets a soft pink "flustered" tint and blinks faster when system
//         load is high (see cpuStressThreshold)
//       * falls fully asleep (eyes closed, motion stops) after the screen
//         has been idle for a while (see idleTimeoutSeconds) -- any input
//         anywhere wakes her back up, same as it un-idles the compositor
//     Otherwise she just idles: a slow bob + sway and an occasional blink.
//   - Left-click to pet her (a little wiggle + a notification reaction).
//   - Right-click to pause enforcement for 5 minutes / resume immediately.
//   - Hover for a tooltip with per-profile detail.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Services.Mpris

Item {
    id: root

    property int blockedCount: 0
    property bool paused: false
    property bool daemonReachable: false
    property var profileNames: []

    // Apps whose appId (window class) counts as "distracting" for Vigi's
    // alert reaction -- edit freely. Matched case-insensitively as a
    // substring, so "discord" also catches "Discord" and similar.
    property list<string> distractingApps: ["discord", "vesktop", "steam", "telegram", "reddit"]
    // 1-minute load average (from /proc/loadavg) above which Vigi looks
    // "flustered" -- not normalized per-core, so tune this to your machine.
    property real cpuStressThreshold: 3.0
    property int idleTimeoutSeconds: 90

    readonly property string activeAppId: (ToplevelManager.activeToplevel?.appId ?? "").toLowerCase()
    readonly property bool distractingAppFocused: root.distractingApps.some(a => root.activeAppId.includes(a))
    readonly property bool musicPlaying: Mpris.players.values.some(p => p.isPlaying)
    readonly property bool stressed: loadAverage1m > root.cpuStressThreshold
    readonly property bool asleep: idleMonitor.isIdle

    property real loadAverage1m: 0
    Timer {
        interval: 5000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: loadAvgProc.running = true
    }
    Process {
        id: loadAvgProc
        command: ["cat", "/proc/loadavg"]
        stdout: StdioCollector {
            onStreamFinished: {
                const first = text.trim().split(" ")[0];
                const value = parseFloat(first);
                if (!isNaN(value)) root.loadAverage1m = value;
            }
        }
    }

    IdleMonitor {
        id: idleMonitor
        timeout: root.idleTimeoutSeconds
        enabled: true
    }

    readonly property var petReactions: [
        "Hey, that tickles!",
        "Boop received.",
        "Still on duty!",
        "You rang?",
        "*happy shield noises*",
        "Vigilance intensifies.",
        "Wheee!",
    ]

    implicitWidth: row.implicitWidth + 16
    implicitHeight: 24

    // A tiny pixel-art Vigi: a 13x12 grid of body/eye/off cells, built
    // entirely from Rectangles (no image asset needed) -- a tapered
    // shield silhouette with two small arm bumps (rows 4-5, separated
    // from the body by a 1px gap so they read as stubs rather than a
    // wider row) and two eye pixels a body-colored pixel apart (a
    // transparent gap there previously showed the bar's own background
    // through and misread as a third dot).
    component VigiPixel: Item {
        id: vigi
        property real cell: 1.7

        readonly property var layout: [
            "....XXXXX....",
            "...XXXXXXX...",
            "..XXXXXXXXX..",
            "..XXXXXXXXX..",
            "X.XXeXXXeXX.X",
            "X.XXXXXXXXX.X",
            "..XXXXXXXXX..",
            "..XXXXXXXXX..",
            "...XXXXXXX...",
            "....XXXXX....",
            ".....XXX.....",
            "......X......",
        ]
        readonly property int cols: 13
        readonly property int rows: 12
        implicitWidth: cols * cell
        implicitHeight: rows * cell

        // Set from outside -- these change Vigi's motion/color but never
        // her silhouette. Priority when several are true at once: asleep
        // beats everything (stops reacting to a screen nobody's looking
        // at); otherwise alert (amber) beats stressed (pink) beats
        // grooving, since "you're looking at something distracting" is
        // more worth noticing than a vibe or a busy CPU.
        property bool grooving: false
        property bool alert: false
        property bool stressed: false
        property bool asleep: false

        readonly property color bodyColor: alert ? "#e0a72a" : stressed ? "#e07ba0" : "#6b8afd"
        readonly property color eyeColor: alert ? "#7a4a12" : stressed ? "#7a1f42" : "#22337a"

        // Smooth blink: eye cells scale their height down and back via a
        // Behavior transition rather than an instant frame swap, so it
        // reads as an eyelid closing instead of a flicker. Asleep forces
        // eyes fully shut; stressed blinks noticeably faster ("flustered").
        property bool blinking: false
        Timer {
            interval: vigi.stressed ? 1200 : 3400
            running: !vigi.asleep
            repeat: true
            onTriggered: {
                vigi.blinking = true;
                blinkOff.start();
            }
        }
        Timer {
            id: blinkOff
            interval: 200
            onTriggered: {
                if (!vigi.asleep) vigi.blinking = false;
            }
        }
        onAsleepChanged: blinking = asleep

        // Idle motion: a continuous bob + sway, sped up and enlarged while
        // grooving to music, and stopped almost entirely while asleep (a
        // faint breathing-like bob instead of standing perfectly still).
        // The "to" targets are live bindings, so a mood change takes
        // effect from the next loop iteration rather than an abrupt
        // mid-swing jump.
        property real bob: 0
        property real sway: 0
        SequentialAnimation on bob {
            loops: Animation.Infinite
            NumberAnimation { to: vigi.asleep ? -0.5 : vigi.grooving ? -5 : -2; duration: vigi.asleep ? 1800 : vigi.grooving ? 260 : 950; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0; duration: vigi.asleep ? 1800 : vigi.grooving ? 260 : 950; easing.type: Easing.InOutSine }
        }
        SequentialAnimation on sway {
            loops: Animation.Infinite
            NumberAnimation { to: vigi.asleep ? 0 : vigi.grooving ? 2.5 : 1; duration: vigi.grooving ? 340 : 1500; easing.type: Easing.InOutSine }
            NumberAnimation { to: vigi.asleep ? 0 : vigi.grooving ? -2.5 : -1; duration: vigi.grooving ? 340 : 1500; easing.type: Easing.InOutSine }
        }

        // A quick shake, fired once whenever "alert" turns on, or on
        // demand when petted (see pet() below).
        property real shakeX: 0
        SequentialAnimation {
            id: shakeAnim
            NumberAnimation { target: vigi; property: "shakeX"; to: 2.5; duration: 55 }
            NumberAnimation { target: vigi; property: "shakeX"; to: -2.5; duration: 55 }
            NumberAnimation { target: vigi; property: "shakeX"; to: 2.5; duration: 55 }
            NumberAnimation { target: vigi; property: "shakeX"; to: 0; duration: 55 }
        }
        onAlertChanged: if (alert) shakeAnim.start()

        function pet() {
            shakeAnim.start();
        }

        Repeater {
            model: vigi.cols * vigi.rows
            Rectangle {
                id: cellRect
                required property int index
                readonly property int row: Math.floor(index / vigi.cols)
                readonly property int col: index % vigi.cols
                readonly property string ch: vigi.layout[row][col]
                readonly property bool isEye: ch === "e"
                visible: ch !== "."
                x: col * vigi.cell + vigi.sway + vigi.shakeX
                width: vigi.cell
                height: isEye && vigi.blinking ? vigi.cell * 0.15 : vigi.cell
                y: row * vigi.cell + vigi.bob + (vigi.cell - height) / 2
                color: isEye ? vigi.eyeColor : vigi.bodyColor
                Behavior on height {
                    NumberAnimation { duration: 110; easing.type: Easing.InOutQuad }
                }
            }
        }
    }

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
            } else if (mouse.button === Qt.LeftButton) {
                vigiPixel.pet();
                const line = root.petReactions[Math.floor(Math.random() * root.petReactions.length)];
                Quickshell.execDetached(["notify-send", "-a", "FocusGuard", "Vigi says:", line]);
            }
        }

        ToolTip.visible: containsMouse
        ToolTip.delay: 400
        ToolTip.text: {
            let base;
            if (!root.daemonReachable)
                base = "FocusGuard: daemon not running";
            else if (root.paused)
                base = "FocusGuard: paused\nRight-click to resume";
            else if (root.blockedCount > 0)
                base = "FocusGuard: blocking " + root.blockedCount + " app(s)\n(" + root.profileNames.join(", ") + ")\nRight-click to pause 5 min";
            else
                base = "FocusGuard: inactive\nRight-click to pause 5 min";
            if (root.asleep)
                base += "\n\nVigi: fast asleep. Move the mouse to wake her.";
            else if (root.distractingAppFocused)
                base += "\n\nVigi: eyeing that window a little suspiciously.";
            else if (root.stressed)
                base += "\n\nVigi: a little flustered -- your CPU's working hard.";
            else if (root.musicPlaying)
                base += "\n\nVigi: vibing to your music.";
            base += "\nLeft-click to pet her.";
            return base;
        }
    }

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: 5

        VigiPixel {
            id: vigiPixel
            Layout.alignment: Qt.AlignVCenter
            grooving: root.musicPlaying
            alert: root.distractingAppFocused
            stressed: root.stressed
            asleep: root.asleep
        }

        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: !root.daemonReachable ? "#888888" : root.paused ? "#f5a623" : root.blockedCount > 0 ? "#e01b24" : "#2ec27e"
        }

        Text {
            visible: root.daemonReachable
            text: root.paused ? "Paused" : root.blockedCount > 0 ? String(root.blockedCount) : "FocusGuard"
            color: "#cfd6f5"
            font.pixelSize: 12
        }
    }
}
