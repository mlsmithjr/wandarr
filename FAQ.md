
# F.A.Q. #

---
### I have multiple graphics cards, can I use them in parallel? ###

Yes, all graphics devices may be used with the correct configuration.
For a simple 1-card config you may have:
```yaml
engines:
  cuda:
    quality:
      medium: "-c:v hevc_nvenc -cq:v 23 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 7M -profile:v main -maxrate:v 7M -preset medium -b_ref_mode 0 -f matroska -max_muxing_queue_size 1024"
```

A redefinition is in order to allocate 2 "slots" for cuda transcoding, and assign each to a unique card using _-hwaccel_device_:
```yaml
engines:
  cuda-1:
    quality:
      medium: "-hwaccel_device 0 -c:v hevc_nvenc -cq:v 23 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 7M -profile:v main -maxrate:v 7M -preset medium -b_ref_mode 0 -f matroska -max_muxing_queue_size 1024"
  cuda-2:
    quality:
      medium: "-hwaccel_device 1 -c:v hevc_nvenc -cq:v 23 -rc vbr -rc-lookahead 20 -bufsize 3M -b:v 7M -profile:v main -maxrate:v 7M -preset medium -b_ref_mode 0 -f matroska -max_muxing_queue_size 1024"
```

Now just change your host definition to use _cuda-1_ and _cuda-2_:
```yaml
  # old
  myhost:
    engines:
    - cuda
  
  # new
  myhost:
    engines:
      - cuda-1
      - cuda-2
```
It does not matter how many cards or machines with multiple cards you have as long as each card has a unique name
and is associated with the right host.  In fact, you can use the same technique to run parallel tasks on the same card,
if it has enough memory and cores to support that.  Just define multiple slots for the same card and assign them all to the host.

---
### Can I only have low, medium, and high qualities? ###

No, those are common example names only.  You can define as many as you need.  Just remember, these are _video_
qualities only.  Audio is defined in the template since audio
is transcoded by the host CPU and therefore no need to have audio options in the GPU engines section.
More sample name:
```yaml
tv-stddef
tv-hd
tv-4k
tv-bw
tv-anime
movie-hd
...
```


---
### The config setup is confusing ###
Yes, it can be, but far simpler that my previous offering. I learned some important lessons with that and 
incorporated into this new project.  The key to remember is that each section defines something specific, and all sections
tie together to make transcoding work across multiple machines, hardware types, and codecs.  It is naturally
going to be a bit confusing given the capabilities but you can always start off simple with just 1 host, 1 engine,
and 1 template (see _config-samples/quickstart.yml_)

Host contains one or more engines which relate to one or more templates.
---
### I liked the flexibility of inheritance and add-ins in pytranscoder.  Why did you remove that? ###
Simple - see comment above.  Configuration of pytranscoder was a beast.  Yes it was very flexible but also
inaccessible by many users.  Also the sheer volume of documentation need to try and unpack it was hard to manage and
bad for short-attention-span folks.  In my years of maintaining that project the main complaint I heard
was about complexity and "I don't need all that flexibility".  I agreed, it was not what most users need.  And besides, the architecture had a limiting
flaw - it could not support multiple video devices on the same machine without major refactoring.  So I went in a new, simpler
direction.  The previous pytranscoder project is still available for forking if anyone needs to continue it.

