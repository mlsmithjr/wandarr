
## wandarr 1.x Examples 

---
There are many different configurations you can create, from the very simple to a complex clustered workhorse.
These are some examples to try and cover the somewhat confusing but powerful configuration.

As mentioned in the README, the configuration is divided into sections:

    1. config - general configuration options
    2. cluster - definition of all hosts that will perform transcoding
    3. engines - definition of all transcoding capabilities and supported qualities
    4. templates - configured templates to determine how to transcode

For these examples I will abbreviate many settings.  You can consult the config-samples folder for full samples.

---

### Running on a Windows machine only, using Intel QSV acceleration

> C:\ wandarr -t norm m:\volumes1\media\video\new\*.mp4

```yaml
cluster:
  mbp:
    os: windows
    type: local
    working_dir: c:/tmp
    ffmpeg: 'c:/ffmpeg/bin/ffmpeg.exe'
    engines:
      - qsv
    status: enabled

engines:
  qsv:
    quality:
      low: "-c:v hevc_qsv -preset medium -qp 23 -b:v 3000K -f matroska -max_muxing_queue_size 1024"
      medium: "-c:v hevc_qsv -preset medium -qp 23 -b:v 7000K -f matroska -max_muxing_queue_size 1024"

templates:
  norm:
    cli:
      audio: "-c:a copy"
      subtitles: "-c:s copy"
    video-quality: medium
    audio-lang: eng
    subtitle-lang: eng
    threshold: 15
    threshold_check: 20
    extension: '.mkv'
```

---

### Add in a Linux server to the configuration above to make a true cluster with file sharing
To do this we need a way to share the media with the linux machine.  
For this case we'll assume the files are on a file server or shared volume on the Windows machine.

Also, since we're defining a _mounted_ type (access to shared files) we are required to have password-less *ssh* access to this linux machine.
Based on the configuration below we should be able to run this command without asking for a password because wandarr will need to do it:
>C:\ ssh happygilmore@192.168.2.65
> 
This involves ssh authentication sharing between Windows and Linux.  If this is more technically detailed than you want, see the next example.
```yaml
  mylinuxserver:
    os: linux
    type: mounted
    working_dir: /tmp
    ip: 192.168.2.65
    user: happygilmore
    ffmpeg: '/usr/bin/ffmpeg'
    engines:
      - qsv
    path-substitutions:
      - 'm:\media /mnt/media'
    status: enabled

This machine also just has Intel QSV capabilities.  Now we have 2 machines that support the _qsv_ engine definition.
We're officially a cluster now!

```
