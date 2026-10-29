# Cherminal user guide

Cherminal connects you to host systems: Linux and Unix servers, IBM
mainframes, IBM i, and serial devices. This guide covers everyday use. Your
administrator may have set some things up for you, so some menus or
settings below can be missing or greyed out; that is on purpose.

On a Mac, the shortcuts below that use Ctrl+Shift are ⌘ instead (⌘O, ⌘N,
⌘F, ⌘P, ⌘C, ⌘V), and the Control key is the host's Ctrl. See
[Cherminal on macOS](MACOS.md#the-keyboard) for the Option key and the keys
Mac keyboards don't have.

## Connecting

- **Open a saved session:** File › Sessions… (Ctrl+Shift+O), pick one and
  press **Connect**, or double-click it. Sessions your administrator shares
  are marked `[shared]`.
- **Connect once without saving:** File › Quick connect… (Ctrl+Shift+N).
- **A different port:** some hosts listen on more than one port, for
  example a mainframe that goes straight to an application menu on 2323.
  Set **Port** in the session, or type `host:2323` in the Host box.
  "default" uses the usual port, shown beside it (23, or 992 with TLS).
- **More than one session:** each opens in its own tab.
- **Signing in:** Cherminal never stores passwords. It asks when the host
  needs one, or the host shows its own sign-on screen.

The first time you connect to an SSH host you may be asked to trust its
key. If your administrator gave you the key's fingerprint, check it matches
before you answer Yes.

## When a session ends

- **Press Enter** in a session that has ended to connect again. Session ›
  Reconnect does the same.
- **Idle timeout:** if you don't type or click in a session for a while
  (15 minutes unless your session says otherwise), Cherminal disconnects it
  and blanks the screen so nobody can read it. A minute before, the status
  bar at the bottom warns you; press any key to stay connected.
- **Dropped connections:** if the session is set to reconnect
  automatically, Cherminal tries again by itself when the network drops,
  and shows "Reconnecting in ... seconds" in the window. You may need to sign
  in again.

## Copy, paste and search

- **Copy:** select text with the mouse, then right-click › Copy (or Edit ›
  Copy). Selected text is also ready to paste with the middle mouse button.
- **Paste:** right-click › Paste, Edit › Paste, or the middle mouse button.
- **Search:** right-click › Search…, or Ctrl+Shift+F. A search bar opens at
  the bottom. Type what you're looking for; Enter (or the up arrow) finds
  the one above, Shift+Enter (or the down arrow) the one below, and it
  wraps around. The gear button offers **Match case**, **Match whole word**
  and **Regular expression**. Esc closes it. Searching covers the screen
  and everything that scrolled off it.
- **Scrolling back:** use the mouse wheel to look at what scrolled off the
  top. Typing returns to the bottom.

Password fields are never copied, searched or printed.

## Colours and text size

- **Colours for this session only:** right-click › Colours for this
  session… (or View › Colours for this session…). Pick a scheme such as
  high contrast or yellow on black, set text and background colours, or
  raise **Minimum contrast**. This changes only the window in front of you
  and stays until you close it, even if you reconnect; the saved session
  and other users are not affected. **Use the session's colours** puts it
  back.
- **Text size:** by default the text grows and shrinks with the window.
  View › Font… picks a different font.

## Printing

- **Print the screen:** the Print key, Ctrl+Shift+P, Session › Print
  screen…, or right-click › Print screen…. If your session has a printer
  set, it prints there straight away; otherwise choose a printer.
- **Host printing:** some host programs print directly to your local
  printer; that happens by itself.

## Uploading files (SSH only)

If your session allows it, drag files from your desktop or file manager
onto the terminal window, or use right-click › Upload files…. Cherminal
asks before sending, and asks again before replacing a file that is
already on the host. Files go to your home folder on the host unless the
session names another folder. Folders can't be uploaded.

## IBM mainframe (3270) and IBM i (5250) sessions

These screens work like the terminals they copy: you type into the fields
on the screen, and nothing goes to the host until you press Enter or a
function key.

| You want to | Press |
|---|---|
| Send the screen | Enter |
| PF1-PF12 / F1-F12 | F1-F12 |
| PF13-PF24 / F13-F24 | Shift+F1-F12 |
| Move to the next or previous field | Tab / Shift+Tab |
| Unlock the keyboard after an error | Escape (Reset) |
| Page backward / forward | PageUp / PageDown |
| Erase to the end of the field | Ctrl+End |
| Clear (3270) | Pause |
| PA1 / PA2 / PA3 (3270) | Alt+F1 / Alt+F2 / Alt+F3 |
| Field Exit (5250) | Keypad Enter |
| Attention (5250) | Shift+Escape |
| System Request (5250) | Alt+Print |

On 3270 screens you can also:

- **Click key names** shown on the screen, such as `PF3=Exit` or `ENTER`,
  instead of pressing the key.
- **Paste** a list into the screen: each line goes into the next input
  field down, and protected text is never overwritten. If the paste stops
  with `X NUM`, a number field was about to get letters.
- **Transfer files** with Session › Transfer file…, if your mainframe has
  IND$FILE. Get to the TSO `READY` prompt (or ISPF option 6, a clear CICS
  screen, or the CMS command line) first, choose send or receive, the host
  file name and your local file, and press the button. A progress window
  shows how it goes.

### Modern view

View › Modern view (Ctrl+Shift+M), or the **Modern view** button beside
the tabs, gives a 3270 or 5250 screen a more familiar look:

- Every input field has a box round it, and the one with the cursor is
  outlined in the cursor colour.
- **Click a field** to put the cursor there. Clicking text you can't type
  over does nothing, and dragging still selects text to copy.
- A **key bar** under the screen has a button for each key the screen
  lists (`F3=Exit` becomes **Exit**, with F3 beside it), **More keys** for
  PA1, Clear, Attention and the rest, and **Send** for Enter.
- **Menus and lists are clickable.** Click a numbered menu option to type
  its number on the `Option ===>` line, or double-click it to choose it
  straight away. On a list with a selection column, click a row to put the
  cursor beside it; double-click it to open it when the screen offers a
  code that only looks (`S`, `1=Select`, `5=Display`). A double-click never
  types a code that changes or deletes anything.
- **Typing mistakes are explained** under the field ("Numbers only in this
  field", "Fill in this field before pressing Enter") instead of locking
  the keyboard, and fields you have changed but not sent yet carry a small
  amber dot.
- **The scroll wheel pages** through screens that page with PF7/PF8 or
  Roll up/down, one page per notch.
- The screen uses the **Graphite** (dark) or **Paper** (light) colours,
  following your desktop. Pick one, or keep the session's own colours,
  with Terminal › **Modern view colours** in the session.

Every key works the same in both views, and the host can't tell them
apart. The switch changes the open tab; to start a session in Modern view
every time, set Terminal › **IBM 3270/5250 view** in the session.

The status bar shows the terminal's state: `X System` or `X SYSTEM` while
the host is busy (wait), `X Protected` or `X II` when you typed somewhere
you can't (press Escape), and the cursor position.

Your session may have its own key layout; File › Edit this session… ›
Keyboard & macros › **Keyboard map…** shows it on a picture of the
keyboard.

## Session logs

If your session keeps a log (its **Logging** tab), the text you saw is
saved in `~/.local/state/cherminal/logs/` unless your administrator chose
another folder. Passwords and what you type are never written to it.
Old log files are deleted by themselves to save space.

## Getting help

Help › About Cherminal shows the version. When you report a problem, say
which session, what you pressed, and the message shown in the window or the
status bar.
