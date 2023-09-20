from __future__ import annotations

from typing import Union, Callable
from pathlib import Path

import gymnasium
import gymnasium as gym
from ocatari import OCAtari
from scobi import Environment as ScobiEnv
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.env_util import make_atari_env
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.utils import set_random_seed
from stable_baselines3.common.vec_env import VecEnv, SubprocVecEnv, VecFrameStack, VecNormalize, DummyVecEnv

from common import FOCUS_FILES_DIR, FOCUS_FILES_DIR_UNPRUNED, REWARD_MODE, MULTIPROCESSING_START_METHOD


def get_env_name(env: Union[gymnasium.Env, OCAtari]):
    return env.spec.name if isinstance(env, gymnasium.Env) else env.game_name


def get_atari_identifier(env_name: str):
    """Extracts game name, e.g.: 'ALE/Pong-v5' => 'pong'"""
    return env_name.split("/")[1].split("-")[0].lower()


def make_scobi_env(name: str,
                   focus_dir: str,
                   pruned_ff_name: str,
                   exclude_properties: bool,
                   rank: int = 0,
                   seed: int = 0,
                   silent=False,
                   refresh=True,
                   reward_mode=0,
                   **kwargs) -> Callable:
    def _init() -> gym.Env:
        env = ScobiEnv(name,
                       focus_dir=focus_dir,
                       focus_file=pruned_ff_name,
                       hide_properties=exclude_properties,
                       silent=silent,
                       reward_mode=reward_mode,
                       refresh_yaml=refresh,
                       hud=True,
                       **kwargs)
        env = Monitor(env)
        env.reset(seed=seed + rank)
        return env

    set_random_seed(seed)
    return _init


def init_train_eval_envs(n_train_envs: int,
                         n_eval_envs: int,
                         seed: int,
                         reward_mode: str,
                         render_eval: bool = False,
                         **kwargs) -> (VecEnv, VecEnv):
    eval_seed = (seed + 42) * 2  # different seeds for eval
    train_env = init_vec_env(n_envs=n_train_envs,
                             seed=seed,
                             train=True,
                             reward_mode=REWARD_MODE[reward_mode],
                             **kwargs)
    eval_render_mode = "human" if render_eval else None
    eval_env = init_vec_env(n_envs=n_eval_envs,
                            seed=eval_seed,
                            train=False,
                            reward_mode=0,
                            render_mode=eval_render_mode,
                            **kwargs)
    return train_env, eval_env


def init_vec_env(name: str,
                 n_envs: int,
                 seed: int,
                 object_centric: bool,
                 reward_mode: int,
                 prune_concept: str = None,
                 exclude_properties: bool = None,
                 frameskip: int = 4,
                 framestack: int = 1,
                 normalize_observation: bool = False,
                 normalize_reward: bool = False,
                 vec_norm_path: str = None,
                 train: bool = False,
                 freeze_invisible_obj: bool = False,
                 render_mode: str = None,
                 render_oc_overlay: bool = False) -> VecEnv:
    """Helper function to initialize a vector environment with specified parameters."""

    if object_centric:
        if prune_concept == "unpruned":
            focus_dir = FOCUS_FILES_DIR_UNPRUNED
            pruned_ff_name = None
        elif prune_concept == "default":
            focus_dir = FOCUS_FILES_DIR
            pruned_ff_name = get_pruned_focus_file_from_env_name(name)
        else:
            raise ValueError(f"Unknown prune concept '{prune_concept}'.")

        # Verify compatibility with Gymnasium
        monitor = make_scobi_env(name=name,
                                 focus_dir=focus_dir,
                                 pruned_ff_name=pruned_ff_name,
                                 exclude_properties=exclude_properties,
                                 reward_mode=reward_mode,
                                 freeze_invisible_obj=freeze_invisible_obj)()
        check_env(monitor.env)
        del monitor

        envs = [make_scobi_env(name=name,
                               focus_dir=focus_dir,
                               pruned_ff_name=pruned_ff_name,
                               exclude_properties=exclude_properties,
                               rank=i,
                               seed=seed,
                               silent=True,
                               refresh=False,
                               reward_mode=reward_mode,
                               render_mode=render_mode,
                               freeze_invisible_obj=freeze_invisible_obj,
                               render_oc_overlay=render_oc_overlay) for i in range(n_envs)]

        if n_envs > 1:
            vec_env = SubprocVecEnv(envs, start_method=MULTIPROCESSING_START_METHOD)
        else:
            vec_env = DummyVecEnv(envs)

        # Wrap with (either existing or new) VecNormalize to normalize obs and/or reward
        if vec_norm_path is not None:
            env = VecNormalize.load(vec_norm_path, vec_env)
            env.training = train
        else:
            env = VecNormalize(vec_env,
                               norm_obs=normalize_observation,
                               norm_reward=normalize_reward,
                               training=train)

    else:
        if n_envs > 1:
            vec_env_cls = SubprocVecEnv
            vec_env_kwargs = {"start_method": MULTIPROCESSING_START_METHOD}
        else:
            vec_env_cls = DummyVecEnv
            vec_env_kwargs = None
        vec_env = make_atari_env(name,
                                 n_envs=n_envs,
                                 seed=seed,
                                 env_kwargs={"render_mode": render_mode},
                                 vec_env_cls=vec_env_cls,
                                 vec_env_kwargs=vec_env_kwargs,
                                 wrapper_kwargs={"frame_skip": frameskip})
        env = VecFrameStack(vec_env, n_stack=framestack)

    return env


def get_pruned_focus_file_from_env_name(name: str) -> str:
    if "ALE" in name:
        env_identifier = get_atari_identifier(name)
    else:
        env_identifier = name
    return f"{env_identifier}.yaml"


def get_focus_file_path(prune_concept: str, env_name: str) -> Path:
    if "ALE" in env_name:
        env_identifier = get_atari_identifier(env_name)
    else:
        env_identifier = env_name

    if prune_concept == "default":
        return Path(FOCUS_FILES_DIR, f"{env_identifier}.yaml")
    elif prune_concept == "unpruned":
        return Path(FOCUS_FILES_DIR_UNPRUNED, f"default_focus_{env_name[4:]}.yaml")
    else:
        raise ValueError(f"Unknown prune concept {prune_concept} given.")
