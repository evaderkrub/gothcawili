"""Run with the SB3 environment after tools/bundle.py (no radio required)."""
from pathlib import Path
import os
import ast
import logging
import sys
import tempfile
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get('GOTHCWILI_RUNTIME', str(ROOT / 'dist/runtime')))
from pwnagotchi import ai
from pwnagotchi.ai.gym import Environment
from pwnagotchi.ai.train import AsyncTrainer
from pwnagotchi.radio_scope import allowed_bssids, permitted


class Epoch:
    def wait_for_epoch_data(self):
        state = {key: 0 for key in ('duration_secs', 'inactive_for_epochs', 'active_for_epochs',
            'missed_interactions', 'num_hops', 'num_deauths', 'num_associations', 'num_handshakes')}
        state.update({key: np.zeros(165) for key in ('aps_histogram', 'sta_histogram', 'peers_histogram')})
        state['aps_histogram'][148] = 1
        state['reward'] = 1.0
        return state


class Agent:
    def __init__(self, path):
        self._config = {'ai': {'enabled': True, 'path': str(path), 'channels': [1, 6, 11, 36, 149, 165],
            'params': {'n_steps': 1, 'learning_rate': .001, 'verbose': 0}}}

    def supported_channels(self):
        return [1, 6, 11, 36, 149, 165]

    def on_ai_policy(self, params):
        self.policy = params

    def on_ai_step(self):
        pass

    def is_training(self):
        return False


class RuntimeTests(unittest.TestCase):
    def test_gymnasium_and_channel_bounds(self):
        from stable_baselines3.common.env_checker import check_env
        agent = Agent('/unused')
        env = Environment(agent, Epoch())
        check_env(env)
        other = Environment(agent, Epoch())
        self.assertEqual(env.action_space.shape, other.action_space.shape)
        params = env.policy_to_params(np.zeros(env.action_space.shape, dtype=int))
        self.assertEqual(params['channels'], [1])
        params = env.policy_to_params(env.action_space.nvec - 1)
        self.assertEqual(params['channels'], agent.supported_channels())
        self.assertEqual(params['min_rssi'], -50)
        self.assertEqual(env.reset()[0].shape, (1, 503))

    def test_training_changes_weights_and_checkpoint_restores(self):
        import torch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'brain.zip'
            agent = Agent(path)
            model = ai.load(agent._config, agent, Epoch())
            before = {key: value.clone() for key, value in model.policy.state_dict().items()}
            trainer = AsyncTrainer.__new__(AsyncTrainer)
            trainer._model, trainer._nn_path = model, str(path)
            model.learn(total_timesteps=5, callback=trainer.on_ai_training_step)
            self.assertEqual(model.num_timesteps, 5)
            self.assertEqual(model._n_updates, 5)
            self.assertTrue(any(not torch.equal(before[key], value) for key, value in model.policy.state_dict().items()))
            trainer._save_ai()
            self.assertTrue(path.is_file())
            self.assertFalse(Path(str(path) + '.tmp.zip').exists())
            restored = ai.load(agent._config, agent, Epoch())
            self.assertEqual(restored.num_timesteps, 5)
            self.assertEqual(restored._n_updates, 5)
            for key, value in model.policy.state_dict().items():
                self.assertTrue(torch.equal(value, restored.policy.state_dict()[key]))
            restored.learn(total_timesteps=2, reset_num_timesteps=False)
            self.assertEqual(restored.num_timesteps, 7)

    def test_active_scope_is_exact_and_fails_closed(self):
        config = {'main': {'allowed_bssids': ['02:AB:00:11:22:33']}}
        self.assertTrue(permitted(config, {'mac': '02:ab:00:11:22:33'}))
        self.assertFalse(permitted(config, {'mac': '02:ab:00:11:22:34'}))
        self.assertFalse(permitted({}, {'mac': '02:ab:00:11:22:33'}))
        for invalid in ('*', '02:ab:00:11:22:*', 'ff:ff:ff:ff:ff:ff', '02:ab:00:11:22:33;quit'):
            with self.assertRaises(ValueError):
                allowed_bssids({'main': {'allowed_bssids': [invalid]}})

    def test_agent_operations_enforce_scope_before_emitting_commands(self):
        # Exercise the generated agent methods without starting its radio threads.
        import pwnagotchi
        tree = ast.parse((Path(pwnagotchi.__file__).parent / 'agent.py').read_text())
        agent_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Agent')
        methods = {node.name: node for node in agent_class.body if isinstance(node, ast.FunctionDef)}
        namespace = {'logging': logging, 'plugins': SimpleNamespace(on=Mock())}
        for name in ('associate', 'deauth'):
            exec(compile(ast.Module(body=[methods[name]], type_ignores=[]), 'agent.py', 'exec'), namespace)
        agent = SimpleNamespace(_config={'main': {'allowed_bssids': ['02:00:00:00:00:01']},
            'personality': {'associate': True, 'deauth': True}},
            is_stale=lambda: False, _should_interact=lambda _: True,
            _view=Mock(), _epoch=Mock(), run=Mock(), _on_error=Mock())
        ap = {'mac': '02:00:00:00:00:02', 'hostname': 'fixture', 'vendor': '',
              'channel': 1, 'clients': [], 'rssi': -40}
        station = {'mac': '02:00:00:00:01:01', 'vendor': ''}
        namespace['associate'](agent, ap)
        namespace['deauth'](agent, ap, station)
        agent.run.assert_not_called()
        ap['mac'] = '02:00:00:00:00:01'
        namespace['associate'](agent, ap)
        namespace['deauth'](agent, ap, station)
        self.assertEqual([call.args[0] for call in agent.run.call_args_list],
                         ['wifi.assoc 02:00:00:00:00:01', 'wifi.deauth 02:00:00:00:01:01'])


if __name__ == '__main__':
    unittest.main()
