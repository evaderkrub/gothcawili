"""CPU A2C backend for the original Pwnagotchi agent on modern Debian.

Uses Stable Baselines3/Gymnasium; models are not TensorFlow/LSTM-compatible.
"""
import logging
from pathlib import Path


def load(config, agent, epoch, from_disk=True):
    settings = config['ai']
    if not settings['enabled']:
        logging.info('ai disabled')
        return False
    import torch
    from stable_baselines3 import A2C
    from stable_baselines3.common.vec_env import DummyVecEnv
    from stable_baselines3.common.sb2_compat.rmsprop_tf_like import RMSpropTFLike
    from pwnagotchi.ai.gym import Environment

    # CM0 shares 416 MiB of RAM with bettercap, the bridge and the OS.
    torch.set_num_threads(1)
    env = DummyVecEnv([lambda: Environment(agent, epoch)])
    path = Path(settings['path'])
    if from_disk and path.is_file():
        # Fail visibly on incompatible/corrupt models; never discard learning.
        model = A2C.load(str(path), env=env, device='cpu')
        logging.info('[ai] restored A2C model: steps=%d updates=%d',
                     model.num_timesteps, model._n_updates)
        return model

    params = dict(settings['params'])
    alpha = params.pop('alpha', .99)
    epsilon = params.pop('epsilon', 1e-5)
    schedule = params.pop('lr_schedule', 'constant')
    if schedule != 'constant':
        raise ValueError('Only constant ai.params.lr_schedule is supported')
    params['device'] = 'cpu'
    params.setdefault('policy_kwargs', {
        'net_arch': [32, 32], 'optimizer_class': RMSpropTFLike,
        'optimizer_kwargs': {'alpha': alpha, 'eps': epsilon},
    })
    model = A2C('MlpPolicy', env, **params)
    logging.info('[ai] CPU A2C ready: %d parameters, channels=%s',
                 sum(p.numel() for p in model.policy.parameters()),
                 env.envs[0]._supported_channels)
    return model
