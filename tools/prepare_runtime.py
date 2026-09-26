"""Build the pinned evilsocket source with the small Debian 13 compatibility patch."""
import argparse
from pathlib import Path
import shutil
import subprocess

UPSTREAM = '9034d55d4d69c98fdd50cdf7ecd698a3248975a4'


def prepare(source, target):
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != UPSTREAM:
        raise RuntimeError('Review compatibility patches for upstream ' + revision)
    shutil.copytree(source / 'pwnagotchi', target / 'pwnagotchi', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (target / 'bin').mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'bin/pwnagotchi', target / 'bin/pwnagotchi')
    shutil.copy2(source / 'LICENSE.md', target / 'LICENSE.md')
    edits = {
        'pwnagotchi/mesh/wifi.py': [('NumChannels = 140', 'NumChannels = 165')],
        'pwnagotchi/ai/parameter.py': [('from gym import spaces', 'from gymnasium import spaces'),
            ('self.min_value <= self.value <= self.max_value',
             'self.min_value <= self.value < self.max_value')],
        'pwnagotchi/ai/gym.py': [
            ('import gym\nfrom gym import spaces', 'import gymnasium as gym\nfrom gymnasium import spaces'),
            ("metadata = {'render.modes': ['human']}", "metadata = {'render_modes': ['human']}\n    render_mode = 'human'"),
            ('self._supported_channels = agent.supported_channels()',
             "self._supported_channels = sorted(set(agent.supported_channels()) & set(agent._config['ai']['channels']))\n"
             "        if not self._supported_channels:\n            raise ValueError('No permitted AI channels supported by the adapter')"),
            ('Environment.params += [', 'self.params = Environment.params + ['),
            ('for p in Environment.params', 'for p in self.params'),
            ('    @staticmethod\n    def policy_size():', '    def policy_size(self):'),
            ('    @staticmethod\n    def policy_to_params(policy):', '    def policy_to_params(self, policy):'),
            ('len(Environment.params)', 'len(self.params)'),
            ('param = Environment.params[i]', 'param = self.params[i]'),
            ("params['channels'] = channels", "params['channels'] = channels or [self._supported_channels[0]]"),
            ('Environment.policy_to_params(policy)', 'self.policy_to_params(policy)'),
            ('featurizer.featurize(state, self._epoch_num)',
             'np.clip(featurizer.featurize(state, self._epoch_num), 0, 1).astype(np.float32).reshape(self._observation_shape)'),
            ('featurizer.featurize(state, 1)',
             'np.clip(featurizer.featurize(state, 1), 0, 1).astype(np.float32).reshape(self._observation_shape)'),
            ("return self.last['state_v'], self.last['reward'], not self._agent.is_training(), {}",
             "return self.last['state_v'], self.last['reward'], False, False, {}"),
            ('def reset(self):', 'def reset(self, *, seed=None, options=None):\n        super().reset(seed=seed)'),
            ("return self.last['state_v']\n", "return self.last['state_v'], {}\n")],
        'pwnagotchi/ai/train.py': [
            ('self._model.save(temp)', "with open(temp, 'wb') as handle:\n            self._model.save(handle)\n            handle.flush()\n            os.fsync(handle.fileno())"),
            ("plugins.on('ai_training_step', self, _locals, _globals)",
             "plugins.on('ai_training_step', self, _locals, _globals)\n        return True"),
            ('self._model.learn(total_timesteps=epochs_per_episode, callback=self.on_ai_training_step)',
             'self._model.learn(total_timesteps=epochs_per_episode, callback=self.on_ai_training_step, reset_num_timesteps=False)\n'
             '                        self._save_ai()\n'
             "                        logging.info('[ai] checkpoint: steps=%d updates=%d', self._model.num_timesteps, self._model._n_updates)")],
        'pwnagotchi/fs/__init__.py': [
            ('from distutils.dir_util import copy_tree', '# Python 3.12+ removed distutils.'),
            ('copy_tree(source, dest, preserve_symlinks=True)',
             'shutil.copytree(source, dest, symlinks=True, dirs_exist_ok=True)')],
        'pwnagotchi/identity.py': [('from Crypto.', 'from Cryptodome.'),
                                  ('import Crypto.', 'import Cryptodome.'),
                                  ('DefaultPath = "/etc/pwnagotchi/"', 'DefaultPath = "/var/lib/gothcwili/identity/"')],
        'pwnagotchi/bettercap.py': [
            ('import websockets', 'import websockets\nfrom websockets.legacy.client import connect'),
            ('websockets.connect(', 'connect('),
            ('auth=self.auth)', 'auth=self.auth, timeout=(3, 15))'),
            ("json={'cmd': command})", "json={'cmd': command}, timeout=(3, 15))")],
        'pwnagotchi/agent.py': [
            ('            s = self.session()\n            self._update_uptime(s)\n            self._update_advertisement(s)\n            self._update_peers()\n            self._update_counters()\n            self._update_handshakes(0)',
             '            try:\n                s = self.session()\n                self._update_uptime(s)\n                self._update_advertisement(s)\n                self._update_peers()\n                self._update_counters()\n                self._update_handshakes(0)\n            except Exception:\n                logging.exception("Statistics update failed; retrying")'),
            ('    def associate(self, ap, throttle=0):',
             '    def associate(self, ap, throttle=0):\n        from pwnagotchi.radio_scope import permitted\n        if not permitted(self._config, ap):\n            return'),
            ('    def deauth(self, ap, sta, throttle=0):',
             '    def deauth(self, ap, sta, throttle=0):\n        from pwnagotchi.radio_scope import permitted\n        if not permitted(self._config, ap):\n            return'),
            ('asyncio.get_event_loop()', 'asyncio.new_event_loop()'),
            ('/root/.pwnagotchi-recovery', '/var/lib/gothcwili/recovery')],
        'pwnagotchi/mesh/utils.py': [
            ('    def _update_advertisement(self, s):\n',
             '    def _update_advertisement(self, s):\n'
             "        if not self._config['personality']['advertise']:\n"
             '            return\n')],
        'pwnagotchi/grid.py': [('timeout=(30.0, 60.0)', 'timeout=(2.0, 5.0)')],
        'pwnagotchi/log.py': [('/root/.pwnagotchi-last-session', '/var/lib/gothcwili/last-session')],
        'pwnagotchi/ui/web/server.py': [("os.environ['WERKZEUG_RUN_MAIN'] = 'true'", '')],
        'pwnagotchi/ui/web/handler.py': [("os.environ['WERKZEUG_RUN_MAIN'] = 'true'", '')],
    }
    for name, replacements in edits.items():
        path = target / name
        text = path.read_text(encoding='utf-8')
        for old, new in replacements:
            if old not in text:
                raise RuntimeError('Patch no longer applies: ' + name + ': ' + old)
            text = text.replace(old, new)
        path.write_text(text, encoding='utf-8', newline='\n')
    # iwlist relies on obsolete Wireless Extensions. Query nl80211's PHY instead.
    path = target / 'pwnagotchi/utils.py'
    text = path.read_text(encoding='utf-8')
    start = text.index('def iface_channels(ifname):')
    end = text.index('\n\ndef led(', start)
    text = text[:start] + '''def iface_channels(ifname):
    from pathlib import Path
    phy = (Path('/sys/class/net') / ifname / 'phy80211').resolve(strict=True).name
    output = subprocess.check_output(['iw', 'phy', phy, 'info'], text=True)
    channels = []
    for line in output.splitlines():
        match = re.search(r'MHz \\[(\\d+)\\]', line)
        if match and '(disabled)' not in line:
            channels.append(int(match.group(1)))
    return channels
''' + text[end:]
    path.write_text(text, encoding='utf-8', newline='\n')
    (target / 'UPSTREAM_COMMIT').write_text(UPSTREAM + '\n')
    overlay = Path(__file__).resolve().parents[1] / 'compat'
    for source_file in overlay.rglob('*.py'):
        destination = target / 'pwnagotchi' / source_file.relative_to(overlay)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('.upstream/pwnagotchi'))
    parser.add_argument('--target', type=Path, default=Path('dist/runtime'))
    args = parser.parse_args()
    prepare(args.source, args.target)
