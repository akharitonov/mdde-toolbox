import argparse
import pickle
import zlib
import sqlite3 as sql

from pathlib import Path

import numpy as np
import pandas as pd


def get_obs_count(db_file_path) -> int:
    """
    Get count of observations in the db file.
    :param db_file_path: Path to the SQLite file with observations.
    :return: Integer count.
    """
    with sql.connect(db_file_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM (SELECT ROWID FROM observations GROUP BY episode, step);")
        return cur.fetchone()[0]


def _traverse_dimension(parent_idx, obs_slice) -> [pd.DataFrame]:
    parent_prefix = "{}_".format(parent_idx) if parent_idx else ''
    if len(obs_slice.shape) > 2:
        slices = []
        for idx, data_slice in enumerate(obs_slice):
            sub_df = _traverse_dimension("{}{}".format(parent_prefix, idx), data_slice)
            slices.extend(sub_df)
        return slices
    else:
        df = pd.DataFrame(obs_slice)
        df.columns = ["{}{}".format(parent_prefix, c) for c in range(0, len(df.columns))]
        return [df]


def write_agent_obs_to_csv(dir_path, agent_id, obs):
    """
    Split agent's observation dimensions into slices and save as a CSV file.
    :param dir_path: Directory where the newly generated CSV file should be placed.
    :param agent_id: ID of the agent, used as part of the file name.
    :param obs: numpy array containing agent's observations.
    """
    slices = _traverse_dimension('', obs)
    df = pd.concat(slices, ignore_index=False, axis=1, sort=False)
    res_file_path = dir_path.joinpath("agent_{}.csv".format(agent_id))
    df.to_csv(res_file_path, decimal='.', sep=',')


def export_observation_csv(db_file_path, dest_path, obs_num):
    """
    Export observations of agents for the selected step into CSV files, one file per agent.
    :param db_file_path: Path to the SQLite file containing observations.
    :param dest_path: Path to the directory where the CSV files should be placed.
    :param obs_num: Observation index.
    """
    if obs_num < 0:
        raise ValueError('Requested observation number should be within range: [1, num-observations]')
    with sql.connect(db_file_path) as conn:
        conn.row_factory = sql.Row
        cur = conn.cursor()
        # Get episode and step for the selected sample
        cur.execute("SELECT episode, step FROM observations "
                    "GROUP BY episode, step ORDER BY episode, step LIMIT 1 OFFSET ?;", [obs_num - 1])
        row = cur.fetchone()
        episode = row['episode']
        step = row['step']
        # Get sample agents
        cur.execute("SELECT agent FROM observations WHERE episode = ? AND step = ?;", [episode, step])
        agents = [a[0] for a in cur.fetchall()]
        # Get observations per agent
        obs_n = {}
        for agent in agents:
            cur.execute("SELECT shape, obs FROM observations "
                        "WHERE episode = ? AND step = ? AND agent = ?;", [episode, step, agent])
            obs_row = cur.fetchone()
            obs_shape = pickle.loads(obs_row['shape'])
            obs = np.frombuffer(zlib.decompress(obs_row['obs']))
            obs = obs.reshape(obs_shape)
            obs_n[agent] = obs
            write_agent_obs_to_csv(dest_path, agent, obs)


def router(config, db_file_path) -> None:
    """
    Execute action according to the specified argument
    :param config: Parsed arguments.
    :param db_file_path: Path to the SQLite file with observations.
    """
    if config.num_observations:
        print(get_obs_count(db_file_path))
    if config.export:
        dest_dir = Path(config.destination)
        dest_dir.mkdir(parents=True, exist_ok=True)
        export_observation_csv(db_file_path, dest_dir, config.observation)
    else:
        raise RuntimeError('No selected execution mode')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--obs-file',
                        help='SQLite observations history file generated by MDDE environment.',
                        type=str,
                        required=True)
    # Work mode
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('-n', '--num-observations',
                            action='store_true',
                            help='Mode: Display the number of observations available in the specified file.')
    mode_group.add_argument('-e', '--export',
                            action='store_true',
                            help='Mode: Export the selected as a CSV file.')
    # Optional parameters
    parser.add_argument('-o', '--observation',
                        type=int,
                        default=None,
                        help='Observation index for export. '
                             'Value should be within range: [1, num-observations]')
    parser.add_argument('-d', '--destination',
                        type=str,
                        default=None,
                        help='Destination folder where the CSVs should be exported.')

    config = parser.parse_args()

    if config.export and not config.observation:
        parser.error("-e/--export requires -o/--observation.")

    if config.export and not config.destination:
        parser.error("-e/--export requires -d/--destination.")

    # Check if the SQLite file exists
    db_file = Path(config.obs_file)
    if not db_file.is_file():
        raise FileNotFoundError('Observations file does not exist: {}'.format(config.obs_file))

    router(config, db_file)