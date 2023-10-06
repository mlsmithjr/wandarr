
import os
from typing import Dict, Any, List
import yaml

from wandarr.template import Template


class Engine:

    def __init__(self, name : str, definition: Dict):
        self.name = name
        self.definition = definition

    def quality(self, name: str) -> bool:
        return name in self.definition.get("quality").get(name)

    def qualities(self):
        return self.definition.get("quality")


class ConfigFile:

    def __init__(self, configuration: Any):
        """load configuration file (defaults to $HOME/.wandarr.yml)"""
        self.settings: Dict = {}
        self.templates: Dict[str, Template] = {}
        self.engines: Dict[str, Engine] = {}
        self.hosts: Dict = {}

        self.directives = dict()
        if configuration is not None:
            if isinstance(configuration, Dict):
                yml = configuration
            else:
                if not os.path.exists(configuration):
                    print(f'Configuration file "{configuration}" not found')
                    exit(1)
                with open(configuration, 'r') as f:
                    yml = yaml.load(f, Loader=yaml.Loader)
            self.settings = yml['config']

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

    def rich(self) -> bool:
        return self.settings.get("rich", False)

    def has_engine(self, name) -> bool:
        return name in self.engines

    def engine(self, name: str) -> Engine:
        return self.engines.get(name)

    def has_template(self, template_name) -> bool:
        return template_name in self.directives

    def get_template(self, name) -> Template:
        return self.templates.get(name, None)

    @property
    def ffmpeg_path(self):
        return self.settings['ffmpeg']

    @property
    def ssh_path(self):
        return self.settings.get('ssh', '/usr/bin/ssh')

    @property
    def default_queue_file(self):
        return self.settings.get('default_queue_file', None)

    @property
    def automap(self) -> bool:
        return self.settings.get('automap', True)
