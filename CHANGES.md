## Changes

#### 06/28/2024 v1.1.1
* Prevent exception if no frame count detected in media metadata

#### 05/16/2024 v1.1.0
* Fixed bug in progress calculation for agent mode.

#### 05/10/2024 v1.0.9
* More updates to compensate for ffmpeg 7.0 occasional missing or erroneous time calculations.

#### 05/2/2024 v1.0.8
* Added compatibility with new ffmpeg (7.0) changes that prevented progress updates.

#### 02/27/2024 v1.0.7
* Added version check to let you know if there is a new release of wandarr.
* Added agent ability access local shares instead of copying files to and from the host.
* Updated agent protocol.
* Agent client/host version compatibility checks.
* More documentation

#### 01/29/2024 v1.0.6
* Minor parsing bug fix for multiple audio and subtitle tracks.  Videos previously encoded are not affected.
* Added -vq (video quality) option to override default quality in the template, reducing the number of templates you have to define if the difference is only the quality.

#### 11/26/2023 v1.0.5
* Added -l (local-only) mode. Skips detection and use of remove machines.
* Internal refactoring to make the code more readible.
* Bug fixes to agent-based host management
* Reduce redundant pings to hosts for awake-checks

#### 10/20/2023 v1.0.4
* Code refactoring cleanup
* Misc small bug fixes related to parsing media technical details

#### 10/16/2023 v1.0.3
* Continue to make small usability tweaks
* Switch to using ffprobe for primary tech details, ffmpeg secondary
* Fixed some parsing issues when certain information isn't present

#### 10/13/2023 v1.0.2
* better error reporting for some activities
* refine the progress bar to provide more information

#### 10/5/2023 v1.0.1 - Initial working version
