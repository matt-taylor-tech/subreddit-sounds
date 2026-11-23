# Getting Reddit API access

subreddit-sounds reads subreddits through Reddit's API, and that needs a Reddit
**client ID and secret**. This guide walks through getting them.

Why it's needed now: Reddit shut down its public RSS feeds in November 2026, and
anonymous access to its JSON endpoints has been blocked since 2025. Since Reddit's
[Responsible Builder Policy](https://support.reddithelp.com/hc/articles/42728983564564)
(November 2025), new API apps need Reddit's approval before they work.

Without credentials the app still runs, but every run that depends on a subreddit
fails (and fires your failure webhook, if you set one). Bandcamp sources keep
working.

## 1. Check for an existing app first

Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) and look under
**developed applications**. An app your account created before November 2025 may
still work. If you have one, skip to [step 5](#5-add-the-credentials-to-the-app).

If clicking **create another app…** gives an error such as *"max clients have
been reached"* or a message about Reddit's policies, self-service creation is
closed for your account and you need to request access (step 2).

## 2. Why not Devvit?

Reddit asks developers to try [Devvit](https://developers.reddit.com/docs/), its
platform for apps that run inside Reddit, before requesting API access. The form
asks what Devvit is missing. For this app the answer is concrete: it writes to
your Spotify account (adding tracks to your playlist needs Spotify's
`playlist-modify` scope), and Devvit's rules say:

> "Account-linked services must be limited to read-only OAuth scopes to external
> user accounts."
> ([Devvit rules](https://github.com/reddit/devvit-docs/blob/main/docs/devvit_rules.md))

It also isn't an in-Reddit experience: there's nothing for a subreddit to
install. It's a small service you run yourself.

## 3. Request access

Open Reddit's [request form](https://support.reddithelp.com/hc/en-us/requests/new)
and choose **Data Access Request**. Then:

| Field | What to enter |
| --- | --- |
| Your email address | Where Reddit should reply |
| Which role best describes your reason… | **I'm a developer** |
| What is your inquiry? | **I'm a developer and want to build a Reddit App that does not work in the Devvit ecosystem.** |
| Reddit account name | Your Reddit username |
| What benefit/purpose will the bot/app have for Redditors? | See below |
| Provide a detailed description… | See below |
| What is missing from Devvit…? | See below |
| Provide a link to source code… | `https://github.com/matt-taylor-tech/subreddit-sounds` |
| What subreddits do you intend to use the bot/app in? | The subreddit(s) your playlist follows, noting it's read-only |
| If applicable, what username will you be operating this Bot/App under? | Leave blank: the app reads as itself, not as a bot account |

Text you can adapt (replace the subreddit with yours, and check the details
against your own settings):

### Benefit / purpose

> It turns what a music community is upvoting into a listenable playlist. Each
> week's top posts in r/YourSubreddit link to songs on YouTube or Spotify; this
> app collects them into a Spotify playlist so people can listen to the
> community's picks in one place instead of clicking through posts one by one.
> It's open source and self-hosted, so any subscriber can run it for the
> subreddits they follow.

### Detailed description

> Read-only. Once a day it authenticates with app-only OAuth (script app,
> client_credentials grant) and makes one GET request per configured subreddit:
> /r/YourSubreddit/top?t=week&limit=100 on oauth.reddit.com.
>
> From each post it uses only the title and the external link URL. For Spotify
> links it takes the track ID; for YouTube links it reads the video title and
> searches Spotify for that song. Matching tracks are added to the operator's own
> Spotify playlist, which is capped at a configurable size (25 by default).
>
> It never posts, comments, votes, sends messages, or reads user profiles,
> private subreddits or any user data. It stores only post titles and link URLs
> (no usernames): in a match cache that expires after 30 days, and in run logs
> kept for 90 days by default.
>
> Volume: about one Reddit API request per day per subreddit.

### What is missing from Devvit

> Writing to the user's Spotify account. The app's whole output is adding tracks
> to the operator's own Spotify playlist, which needs Spotify's playlist-modify
> write scope. Devvit's rules limit account-linked services to read-only OAuth
> scopes on external accounts, so this can't be built on Devvit.
>
> It also isn't an in-Reddit experience: it has no UI or behaviour inside a
> subreddit and isn't something a community installs. It's a small self-hosted
> service that one person runs for their own playlist.

Reddit replies by email. Approval isn't guaranteed and there's no published
turnaround time.

## 4. Create the app

Once approved (or if you already had access), go to
[reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) and choose
**create another app…**:

| Field | Value |
| --- | --- |
| name | `subreddit-sounds` |
| type | **script** (for personal use) |
| description | Optional |
| about url | `https://github.com/matt-taylor-tech/subreddit-sounds` |
| redirect uri | `http://localhost:8000` |

The redirect URI is never used: the app authenticates as itself
(`client_credentials`), not by sending you through a Reddit login. Reddit just
requires a valid URL. It's unrelated to the Spotify redirect URI.

The **client ID** is the short string just under the app's name. The **secret**
is labelled *secret*. The app never needs your Reddit password.

## 5. Add the credentials to the app

In subreddit-sounds, open **Settings → Reddit**:

1. Paste the **Client ID** and **Client Secret**.
2. Set the **User-Agent** to name your Reddit account, as Reddit asks:
   `web:subreddit-sounds:<version> (by /u/<your username>)`.
3. **Save**, then press **Test Reddit connection**. It fetches a fresh token and
   reads a few of this week's top posts from one of your playlists' subreddits.

If the test passes, the next scheduled sync reads Reddit again. You can also
press **Run now** on the Playlists page.
