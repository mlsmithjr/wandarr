## wandarr - the Distributed Transcoding Toolkit
This CLI tool is a transcoding workflow manager that makes transcoding video files easier and optionally across multiple
machines in parallel, using ffmpeg. It is the successor to pytranscoder and is based on the fundamental codebase  of that project.

#### Features:
* Sequential or concurrent transcoding. 
* Concurrent mode allows you to make maximum use of your 
nVidia CUDA-enabled graphics card or Intel accelerated video (QSV)
* Preserves all streams but allows for filtering by audio and subtitle language.
* Configurable transcoding templates
* Transcode from a list of files (queue) or all on the command line
* Clustering allows use of other machines See [Cluster.md](https://github.com/mlsmithjr/transcoder/blob/master/Cluster.md) for details.
* On-the-fly compression monitoring and optional early job termination if not compressing as expected.

#### Requirements

* Linux or MacOS, Windows. 
* latest *ffmpeg* (3.4.3-2 or higher, lower versions may still work)
* nVidia graphics card with latest nVidia CUDA drivers (_optional_)
* Intel CPU with QSV enabled (_optional_)
* Python 3 (3.10 or higher)

### Installation
```bash
pip3 install wandarr
```

#### Upgrading

Whatever method above for installing works for you, just use the --upgrade option to update, ie:
```bash
pip3 install --upgrade wandarr
```

### Support
Please log issues or questions via the github home page for now.


### Configuration

There is a supplied sample *wandarr.yml* config file, or you can download it from the git home.  This can be customized all you like, however be
sure to preserve the YAML formatting. Either specify this file on the commandline with the *-y* option
or copy it to your home directory as *.wandarr.yml* (default)

In short, you will define your machine(s) used for transcoding, the transcoding capabilities of those machines, and template to tie it all together.

There are 4 sections in the file:

#### Section 1 - config - Global configuration information

Sample
```yaml
config:
  ffmpeg:   '/opt/homebrew/bin/ffmpeg'  # path to ffmpeg for this config
  rich:     yes                         # use rich text library for nicer output
```

#### Section 2 - host definition(s)

The *cluster:* section is where you define all the machines in your network you intend to use for asynchronous transcoding jobs.
This is optional - you need only define a single machine if that's all you are using.

Single-host sample - you can just start out like this:
```yaml
cluster:
  mbp:
    os: macos
    type: local                 # the host you will run wandarr on.
    working_dir: /tmp           # best if this is an SSD
    ffmpeg: '/opt/homebrew/bin/ffmpeg'
    engines:
      - vt
    status: enabled
```

Multi-host Sample:

All fields in these samples are required for their respective host type and there are no optional ones.
This sample cluster defines 3 hosts that will participate in a transcode job. The video files reside on a NAS.

The first host, "homeserver", is an Ubuntu machine with an NFS mount to the NAS (type=mounted). It has both a QSV-enabled
Intel CPU and a discrete nVidia graphics card with CUDA support.

The second host, "winpc", is a Windows 11 machine running wandarr as an agent (type=agent).  It also has an nVidia card
installed but not QSV-enabled.

The final host, "mbp", is a MacBook Pro (M1 Pro) where this process is running from (type=local).  It will also handle
transcoding using the Apple VideoToolbox hardware acceleration feature.

```yaml
cluster:
  # sample linux machine with an Intel i5 CPU/iGPU and nVidia graphics card
  homeserver:
    os: linux
    type: mounted                 # files to transcode are available via a network mount
    working_dir: /tmp             # dir to use for temp files during transcode, best to place on an SSD
    ip: 192.168.2.64              # ip or hostname of the machine
    user: marshall                # your ssh user login name. You must be able to ssh into this host w/o a password
    ffmpeg: '/usr/bin/ffmpeg'     # location of ffmpeg on the host
    engines:                      # list one of more of the video "engines" defined in the next section.  This identifies
                                  # the video handling capabilities of the host. In this sample, this host can do QSV and CUDA
      - qsv
      - cuda
      - cpu
    path-substitutions:           # for mounted types only - maps the local drive path to remote mounted one (more later)
      - '/Volumes/USB11/ /mnt/media/'
      - '/Volumes/media/ /mnt/media/'
      - '/mnt/downloads/ /mnt/downloads/'
    status: enabled               # enabled or disabled

  # sample Windows 11 machine with an nVidia graphics card
  winpc:
    os: win10
    type: agent                   # this host is running wandarr in agent mode (more later). No mounts or ssh used.
    ip: 192.168.2.61
    ffmpeg: 'c:\ffmpeg\bin\ffmpeg.exe'
    engines:
      - cuda
      - cpu
    working_dir: 'c:/temp'
    path-substitutions:
      - '/Volumes/media m:'
      - '/Volumes/USB11/media m:'
      - '/mnt/merger/media/video/ n:video\'
      - '/mnt/downloads/ z:\'
    status: enabled

  # sample MacBook Pro (M1 Pro silicon) using VideoToolkit hw acceleration
  mbp:
    os: macos
    type: local                 # the host you will run wandarr on. Not required if you will not transcode on this machine
    working_dir: /tmp
    ffmpeg: '/opt/homebrew/bin/ffmpeg'
    engines:
      - vt
      - cpu
    status: enabled
```

Host Types:

- local
  - The machine running wandarr.  It's either your only single transcoding machine, or a member of a cluster. If you have multiple machines and will not use your "local" machine to also transcode them you need no local host defined.
- mounted
  - This machine can access the media via a network mount. Besides local, this is the next fasted option as the files can be immediately accessed.  You must have an ssh password-less login to this host. You can use the ssh-copy_id tool to establish trust between machines.
- streaming
  - This machine has no network mount, so copy the file to it over first, transcode, then copy the resulting file back.  This still requires ssh access like mounted.
- agent
  - This machine is running as a remote wandarr agent and requires no ssh or mounted filesystem. The tool must be installed there and started with ```wandarr --agent```.  It will use port 9567 to communicate with wandarr on your local machine to transfer files and perform transcoding. Note that this is insecure - this should only be used on your private network where you have control.

#### Section 3 - engines
This section defines the video transcoding capabilities of your host(s).  The labels and values can be anything you like.
Each section under *engines* defines a hardware capability.  Here you see 3 - vt, qsv, and cuda representing the 3 types of hardware transcoding available to the sample hosts.
Each section under *quality* defines as many named configurations as you need.  In the sample here you see low, medium, high, and copy.
These are ffmpeg options that control how your video is transformed.  These are *only* the video options as they are the ones that can vary between hardware.
While these are usable samples, you may alter then to suit your needs or add many more.
Also keep in mind you do not need to use hardware acceleration, but it does makes things go faster.

Sample:
```yaml
engines:
  vt:         # videotoolkit hardware acceleration
    quality:
      low: "-c:v hevc_videotoolbox -qp 25 -b:v 5000K -f matroska"
      medium: "-c:v hevc_videotoolbox -preset medium -qp 23 -b:v 6000K -f matroska -max_muxing_queue_size 1024"
      high:  "-c:v hevc_videotoolbox -preset medium -qp 21 -b:v 8000K -f matroska -max_muxing_queue_size 1024"

  qsv:      # qsv hardware acceleration
    quality:
      medium: "-c:v hevc_qsv -preset medium -qp 23 -b:v 7000K -f matroska -max_muxing_queue_size 1024"
      high: "-c:v hevc_qsv -preset medium -qp 21 -b:v 7000K -f matroska -max_muxing_queue_size 1024"

  cuda:     # nvidia hardware acceleration
    quality:
      high: "-c:v hevc_nvenc -cq:v 21 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 6M -profile:v main -maxrate:v 6M -preset medium -b_ref_mode 0 -f matroska -max_muxing_queue_size 1024"
      medium: "-c:v hevc_nvenc -cq:v 23 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 7M -profile:v main -maxrate:v 7M -preset medium -b_ref_mode 0 -f matroska -max_muxing_queue_size 1024"

  cpu:      # transcode using only the CPU (ick!)
    quality:
      high-hevc: "-c:v hevc -cq:v 21 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 6M -profile:v main -maxrate:v 6M -preset medium -b_ref_mode 0 -f matroska -max_muxing_queue_size 1024"
      medium-hevc: "-c:v hevc -cq:v 23 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 7M -profile:v main -maxrate:v 7M -preset medium -b_ref_mode 0 -f matroska -max_muxing_queue_size 1024"
      high-264: "-c:v x264 -cq:v 21 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 6M -profile:v main -maxrate:v 6M -preset medium -b_ref_mode 0 -f matroska -max_muxing_queue_size 1024"
      medium-264: "-c:v x264 -cq:v 23 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 7M -profile:v main -maxrate:v 7M -preset medium -b_ref_mode 0 -f matroska -max_muxing_queue_size 1024"
      copy: "-c:v copy -f matroska"
```

#### Section 4 - templates
Templates define overall how to handle a video.  As with engine definitions above, the *cli* section here defines the ffmpeg options for handling audio and subtitles.

In the samples below you will see examples of video-only transcoding (preserve audio as-is), full audio and video transcoding, 
and special case template used just to scrub out unwanted languages.

Note the *video-select* element.  This is used to complete the linkage from template to engine to hosts.

Sample:
```yaml
templates:
  vid-only:                   # name of the template - you will use this on the commandline
    cli:                      # section for non-video ffmpeg commandline options
      audio-codec: "-c:a copy"
      subtitles: "-c:s copy"
    video-select: medium      # match this template to the "medium" quality defined in *engines*
    audio-lang: eng           # preserve only English audio tracks (opt).
    subtitle-lang: eng        # preserve only English subtitle tracks (opt).
    threshold: 15             # minimum required compression is %15, or terminate transcode (opt)
    threshold_check: 20       # start checking for minimum threshold at 20% (opt)
    extension: '.mkv'         # use this file extension

  vid-only-anime:
    cli:
      audio-codec: "-c:a copy"
      subtitles: "-c:s copy"
    video-select: medium
    audio-lang: "eng jpn"     # preserve English and Japanese audio
    subtitle-lang: eng
    threshold: 15
    threshold_check: 20
    extension: '.mkv'

  best-medium:
    cli:
      audio-codec: "-c:a ac3 -b:a 768k"
      subtitles: "-c:s copy"
    video-select: medium
    audio-lang: eng
    subtitle-lang: eng
    threshold: 15
    threshold_check: 20
    extension: '.mkv'

  best-medium-anime:
    cli:
      audio-codec: "-c:a ac3 -b:a 768k"
      subtitles: "-c:s copy"
    video-select: medium
    audio-lang: "eng jpn"
    subtitle-lang: eng
    threshold: 15
    threshold_check: 30
    extension: '.mkv'

  scrub:        # this template used only to scrub out undesired audio and subtitle tracks. no transcoding done.
    cli:
      audio-codec: "-c:a copy"
      subtitles: "-c:s copy"
    video-select: copy
    audio-lang: eng
    subtitle-lang: eng
    extension: '.mkv'

  scrub-anime:  # this template used only to scrub out undesired audio and subtitle tracks. no transcoding done.
    cli:
      audio-codec: "-c:a copy"
      subtitles: "-c:s copy"
    video-select: copy
    audio-lang: "eng jpn"
    subtitle-lang: eng
    extension: '.mkv'
 ```

### Putting it all together

Here's how to read the samples above in their entirety.

In the *vid-only* template above, we defined the ffmpeg options to handle audio and subtitles.  In this case, we're just copying with no changes.
Now we need to know the ffmpeg options for handling video.
The video-select value of *medium* matches all *medium* definitions in engines.  This tells wandarr that any hosts that match an
engine definition containing a *medium* will be a eligible match for this template.  So for medium we have told wandarr how to transcode
video for video toolbox, intel qsv, and nvidia cuda.  Whichever hosts are associated to those engines may be selected to do the job.

So, a template relates to an engine quality. A quality defines ffmpeg options for all supported hardware to accomplish the same result.
A host relates to one or more engines. This is how a host is selected for transcoding, and how to do it.

You can be as basic or complex as you need.  The typical user only needs 2 or 3 templates.

### Running

**The default behavior is to remove the original video file after encoding** and replace it with the new version.
If you want to keep the source *be sure to use the -k* parameter.  The work file will be placed in the same
folder as the source with the same name and a .tmp extension while being encoded.

```text
usage: main.py [-h] [-v] [-i] [-k] [--dry-run] [-y CONFIGFILE_NAME] [--agent] [-t TEMPLATE] [--hosts HOST_OVERRIDE] [--from-file FROM_FILE] [filename ...]

wandarr (ver 1.0.0)

positional arguments:
  filename

options:
  -h, --help            show this help message and exit
  -v                    verbose mode
  -i                    show technical info on files and stop
  -k                    keep source (do not replace)
  --dry-run             Test run, show steps but don't change anything
  -y CONFIGFILE_NAME    Full path to configuration file. Default is ~/.wandarr.yml
  --agent               Start in agent mode on a host and listen for transcode requests from other wandarr.
  -t TEMPLATE           Template name to use for transcode jobs
  --hosts HOST_OVERRIDE
                        Only run transcode on given host(s), comma-separated
  --from-file FROM_FILE
                        Filename that contains list of full paths of files to transcode
```

#### Examples:

To get help and version number:
```bash
   wandarr -h
```

Show me the technical goods on some files:
```bash
   wandarr -i *.mkv
```

To transcode 2 files using a specific template:
```bash
    wandarr -t my_fave_x264 /tmp/video1.mp4 /tmp/video2.mp4
```

To auto transcode everything listed in a specific file:
```bash
    wandarr -t tv --from-file /tmp/queue.txt
```
To do a test run without transcoding:
```bash
    wandarr -t movie-high --dry-run atestvideo.mp4
```

To use a specific yml file:
```bash
    wandarr -y /home/me/etc/quickstart.yml -t tv *.mp4
```

To transcode on a specific host only:
```bash
    wandarr -t tv --host workstation *.mp4
```
