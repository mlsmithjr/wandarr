
## wandarr 1.x Agent mode

---
Running in agent mode was created by necessity due to some nefarious security and networking changes made in Windows 11 and WSL2.
It has become very difficult to use ssh-based client/server connectivity when using Windows 11 as the primary host (local host).
There are several complicating factors:

1. Using the built-in Windows 11 OpenSSH server prevents access to mapped network drives.  So if you have drive M: mapped to, say, a NAS where your media is stored - that drive is not accessible to an ssh session.
2. Using WSL2 requires some sophisticated proxying in order to ssh to it because it now assigns a private IP address to the WSL VM.

Due to these very user un-friendly issues the agent mode was created. **But please keep in mind - the agent listens on an unsecured connection.** 
You are required to secure your own network from access by bad actors.  But the wandarr agent code (agent.py)
only reads and writes to the temp dir or shared network drive you specify.  It does not alter any system settings.
Feel free to review the code to put yourself at ease. I hope to eventually make it more secure but only if it can
be done that doesn't require users to have a PHD in security.

### Scenario 1:
Your primary wandarr machine is a linux workstation.  You want to create a small 2-machine cluster with your Windows machine
to do multiple encodes in parallel.  Your Windows machines does not have access to the NAS where the media originates, or
you just can't get _mounted_ mode working.  The solution is to define your Windows machine host type as _agent_.

```yaml
  winpc:
    os: windows
    type: agent
    ip: 192.168.2.61
    user: mal
    ffmpeg: 'c:\ffmpeg\bin\ffmpeg.exe'
    engines:
      - qsv
    working_dir: 'c:/temp'
    status: enabled
   ```

Install wandarr on the Windows machine as you did on the primary one.

When ready to transcode, start wandarr on the Windows machine like:
> C:\ wandarr --agent

It will now wait for a connection from your linux workstation and "talk" to it to exchange information.

Now if you start wandarr on the primary,
> $ wandarr -t norm /mnt/media/video/inbox/*.mp4

...it will use your local machine and the Windows one to transcode your files.
This effectively replaces _ssh_ as the mechanism for your primary machine to start ffmpeg on remote machines.
Furthermore, in this sample configuration the file being encoded is uploaded to the Windows machine via the wandarr agent,
transcoded via ffmpeg, then downloaded back and written over the original.

![unshared agent mode](https://github.com/mlsmithjr/wandarr/tree/master/diagrams/agent-unshared.jpg)

---
### Scenario 2:
The process of copying files from the primary to the worker (Windows) machine and back is slow.  I want to setup a share and access
it from Windows so that all media is accessible from any machine.
This involves mapping a network share to a drive in Windows and adding a path substitution section to the config.

```yaml
  winpc:
    os: windows
    type: agent
    ip: 192.168.2.61
    user: mal
    ffmpeg: 'c:\ffmpeg\bin\ffmpeg.exe'
    engines:
      - qsv
    working_dir: 'c:/temp'
    path-substitutions:
      - '/mnt/media m:'
    status: enabled
   ```
This informs wandarr that any file pathname that starts with "/mnt/media" can be access on the Windows host using "m:"

So for this,
> $ wandarr -t norm /mnt/media/video/inbox/testvideo.mp4

wandarr checks to see if there is a path-substitutions section for the host.  If so it tries to make a new pathname
that the host can access.  So _/mnt/media/video/inbox/testvideo.mp4_ becomes _m:/video/inbox/testvideo.mp4_ on the Windows machine.
This is how all shared mapping works in wandarr. 

If everything is setup correctly on Windows then the transcode will start immediately since there is no need for wandarr
to exchange files with it.

**Remember**, each machine will probably mount your shared filesystems by different names
and wandarr needs to know how to translate those to pass to ffmpeg for a given host.


