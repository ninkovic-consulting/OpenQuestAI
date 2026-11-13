# Talk to your assistant from your phone (Discord)

You can message your assistant from your phone through a Discord bot that belongs to you. You type or send a voice note in a direct message; the assistant on your Mac answers there. Results of automations, warnings and requests that need your yes can come to the phone too.

This guide is for anyone running Vision on their own Mac. It takes about ten minutes.

> **Status.** The channel is tested against a local stand-in for Discord, not yet against the live service by many people. If a step does not behave as written here, please open an issue and say which step.

## How it works, in short

- The bot is **yours**: you create it in Discord's Developer Portal, and only your Mac holds its token.
- Your Mac **connects out** to Discord. Nothing on your Mac listens for the internet, and you open no ports.
- The bot answers **one Discord account**: the one you pair with a one-time code. Everyone else gets one fixed line and nothing runs.
- Your Mac must be on and Vision running for the bot to answer.

## What you need

- Vision running on your Mac, with your Anthropic API key already set.
- A Discord account, and the Discord app on your phone, signed in to that account.

## Set it up

### 1. Create your bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and sign in.
2. Press **New Application**, give it a name (for example your assistant's name), accept the developer terms if Discord asks, and press **Create**.
3. On **General Information**, copy the **Application ID**. You need it in step 2.
4. Open **Installation** and make sure **User Install** is ticked.

You do not need to switch on any "Privileged Gateway Intents", and the bot needs no permissions.

Optional: on the **Bot** page, switch **Public Bot** off so nobody else can add your bot anywhere. The bot ignores servers and answers nobody but you either way.

### 2. Add the bot to your own account

Open this link in a browser where you are signed in to Discord, with your Application ID in place of `YOUR_APPLICATION_ID`, and press **Authorize**:

```
https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&integration_type=1&scope=applications.commands
```

The page says the app wants to create commands and send you direct messages. That is all it asks for.

### 3. Copy the bot's token

1. In the Developer Portal, open your application's **Bot** page.
2. Press **Reset Token** and confirm.
3. Copy the token. Discord shows it only once.

Treat the token like a password. Do not post it, commit it or paste it into a chat. Anyone who has it can run your bot.

### 4. Give the token to Vision

1. In Vision, open **Settings** (Cmd+,) and choose **Phone**.
2. Paste the token into **Bot token** and press **Save token**.
3. Vision checks the token with Discord. The status line should read **Connected to Discord as** followed by your bot's name.

The token is stored in the macOS Keychain. Vision never shows it again, and it is never written to a file, a log or a backup.

### 5. Pair your phone

1. Still in **Settings, Phone**, press **Show a pairing code**. You get six digits that are valid for ten minutes.
2. In Discord on your phone, open a direct message with your bot (see below) and send those six digits as a message, for example `482913`. The code is shown on the Mac; the words "Show a pairing code" are the button's name, not something to send.
3. The bot answers "Paired. This chat now talks to …", and Settings shows who is paired.

**Opening a direct message with your bot.** After step 2 the bot is one of your apps, and you can message it without sharing a server with it. Open its profile in Discord and choose **Message**, or type its name into **Find or start a conversation**. If Discord does not offer that, use the fallback:

1. Create a private server of your own (the **+** in Discord's server list).
2. Add the bot to it by opening this link and choosing that server:
   `https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&scope=bot&permissions=0`
3. In the server's member list, tap the bot and choose **Message**.

The bot never reads or answers in the server; it is only there so you can reach its direct messages.

## Use it

Everything happens in the direct message with your bot.

| You send | What happens |
|---|---|
| Any text | It becomes a turn for the assistant, exactly as if you had typed it at the Mac. The reply comes back as a message. |
| A voice note | It is turned into words on your Mac, shown back to you as "Heard: …", and answered. |
| `status` | The assistant's state, whether Claude or the local model is answering, and this month's spend. |
| `stop` | Stops the reply in progress and drops your waiting messages. |
| `help` | A reminder of these commands. |

Things to know:

- **One at a time.** A message from the phone waits until the assistant is idle. Up to five can wait; after that the bot asks you to send it again in a moment.
- **Same assistant, same memory.** Phone turns use the same memory, tools, budget and history as turns at the Mac. In the window they are labelled "You, from the phone".
- **Quiet at home.** Replies to the phone are not spoken on the Mac unless you switch that on.
- **Voice notes need the speech models.** Download them in **Settings, Voice**. Until then the bot says so and text still works.
- **Only text and voice notes are read.** Other attachments are ignored, and the bot tells you.

### What the assistant sends you

Each of these has its own switch under **Send to the phone**:

- **Automation results:** what a scheduled automation came to.
- **Warnings and errors:** for example the budget warning.
- **Requests that need your yes:** see below.
- **Results of jobs you handed off from the phone:** when you ask from the phone for one of the other agents to do something, the assistant's report of the result comes back to the phone.

### Approving from the phone

Some actions wait for your yes. When one does, the bot sends the request with **exactly** what will be done and, when it may be approved from the phone, **Yes** and **Not now** buttons. After you answer, the message changes to say what happened.

- **Shell commands are never approved from the phone.** The message tells you to approve at the Mac.
- **Running a program in a project** (an agent's `run_program`) is off for the phone by default, because it runs code. You can allow it under **Approvals from the phone**.
- A request whose detail is too long to show in full also waits at the Mac, so you never approve something you could not read.
- A press counts only from your paired account, in the direct message, while the request is still open.
- If nobody answers in time, the action does not run.

## Settings reference

All under **Settings, Phone**. Changes apply at once.

| Block | What it does |
|---|---|
| Channel | The connection's state, and **Turn the channel off** to stop sending to and reading from Discord without unpairing. |
| Bot token | **Save token** or **Replace token**, and **Verify** to ask Discord who the bot is. |
| Pairing | **Show a pairing code**, who is paired, and **Unpair**. |
| Send to the phone | The four switches described above. |
| Replies | Also speak replies to the phone on the Mac; answer a voice note with a voice note too. |
| Approvals from the phone | Which tools may be approved with Yes on the phone. |
| Voice notes | Whether this Mac can read voice notes, and what is missing if not. |

## Safety, plainly

- **Who is answered.** Only the paired account, and only in a direct message. Anyone else, and everyone before pairing, gets one fixed line at most once a minute. Each attempt is written to the audit log with who it was, never what they wrote.
- **The pairing code** is six digits, lasts ten minutes, and is used up by a match or by five wrong tries. While a phone is paired, no new code is issued; unpair first.
- **The token** lives in the Keychain. It is never logged, never returned to the window, never written to `phone.json` and never put in a backup.
- **The gate still applies.** Nothing sent from the phone goes around the rules for asking first. `stop` only stops; it approves nothing.
- **If your phone is lost:** on the Mac, press **Unpair**. To be thorough, also press **Reset Token** in the Developer Portal; the old token stops working at once.

## When something goes wrong

| What you see | What to do |
|---|---|
| "Discord refused the token." | Reset the token in the Developer Portal and save the new one. A token works only until the next reset. |
| "Stored, but Discord could not be reached to check it." | The Mac is offline. It connects by itself once Discord answers. |
| "Reconnecting to Discord…" | The connection dropped (sleep, network). It keeps trying by itself with growing pauses. |
| The bot answers "This is a private assistant and does not answer here." | You are not paired, or you are writing from a different account. Send the six digits from **Show a pairing code**. |
| The code is not accepted | It expired after ten minutes or was used up by five wrong tries. Press **Show a pairing code** again. |
| "Store the bot token first." | Pairing needs a stored token; do step 4. |
| No answer at all, and the bot shows as offline in Discord | The bot is not connected. Check that Vision is running on the Mac, that the token is saved (step 4), that the channel is on, and that the status line says Connected. A connected bot always answers something, even to a stranger. |
| "I can't listen to voice notes yet" | Download the speech models in **Settings, Voice**, or type. |
| You cannot find where to message the bot | Use the private-server fallback in step 5. |

## Turn it off or remove it

- **Pause:** **Turn the channel off**. Pairing and token stay.
- **Unpair:** the bot then answers nobody until you pair again.
- **Start over:** **Settings, Reset, Start over** backs up and clears the phone's settings and pairing. The token stays in the Keychain unless you also choose to remove the keys.
- **Remove the bot entirely:** delete the application in the Developer Portal.
