import os
import sys
from typing import Dict, Any
import yaml

from wandarr.template import Template


class Engine:

    def __init__(self, name: str, definition: Dict):
        self.name = name
        self.definition = definition

    def qualities(self):
        return self.definition.get("quality")


class ConfigFile:

    def __init__(self, configuration: Any):
        """load configuration file (defaults to $HOME/.wandarr.yml)"""
        self.settings: Dict = {}
        self.templates: Dict[str, Template] = {}
        self.engines: Dict[str, Engine] = {}
        self.hosts: Dict = {}

        self.directives = {}
        if configuration is not None:
            if isinstance(configuration, Dict):
                yml = configuration
            else:
                if not os.path.exists(configuration):
                    print(f'Configuration file {configuration} not found')
                    sys.exit(1)
                with open(configuration, 'r', encoding="utf8") as f:
                    yml = yaml.load(f, Loader=yaml.Loader)
            self.settings = yml['config']

            # verify ffmpeg
            config = yml.get("config", {})
            ffmpeg_path = config.get("ffmpeg")
            if not os.path.exists(ffmpeg_path):
                raise ValueError(
                    (f"ffmpeg not found at configured location {ffmpeg_path} "
                     "- please correct config/ffmpeg setting"))

            #
            # load cluster hosts
            #
            self.hosts = yml["cluster"]

            #
            # load templates
            #
            if "templates" in yml:
                for name, template in yml['templates'].items():
                    self.templates[name] = Template(name, template)

            #
            # load engines
            #
            if "engines" in yml:
                for name, engine_def in yml['engines'].items():
                    self.engines[name] = Engine(name, engine_def)

    @property
    def rich(self) -> bool:
        return self.settings.get("rich", True)

    @rich.setter
    def rich(self, v):
        self.settings["rich"] = v

    def engine(self, name: str) -> Engine:
        return self.engines.get(name)

    def get_template(self, name) -> Template:
        return self.templates.get(name, None)

    @property
    def ffmpeg_path(self):
        return self.settings['ffmpeg']

    @property
    def ssh_path(self):
        return self.settings.get('ssh', '/usr/bin/ssh')
