import os
import io
import glob
import psycopg2
import pandas as pd
import numpy as np
from scripts.sql_queries import *

bulk_song_df_dict = {
    'songs': pd.DataFrame(columns=['song_id', 'title', 'artist_id', 'year', 'duration']),
    'artists': pd.DataFrame(columns=['artist_id', 'name', 'location', 'latitude', 'longitude'])
}

bulk_log_df_dict = {
    'time': pd.DataFrame(columns=['start_time', 'hour', 'day', 'week', 'month', 'year', 'weekday']),
    'users': pd.DataFrame(columns=['user_id', 'first_name', 'last_name', 'gender', 'level']),
    'songplays': pd.DataFrame(columns=['start_time', 'user_id', 'level', 'song_id', 'artist_id', \
                                       'session_id', 'location', 'user_agent']),
}


def process_song_file(cur, filepath):
    global bulk_df_dict

    # open song file
    df = pd.read_json(filepath, lines=True)

    # Round the duration to the closest second
    df['duration'] = int(round(df['duration']))

    # append song record
    song_df = df[['song_id', 'title', 'artist_id', 'year', 'duration']]
    bulk_song_df_dict['songs'] = bulk_song_df_dict['songs'].append(song_df, sort=False)

    # append artist record
    artist_df = df[['artist_id', 'artist_name', 'artist_location', 'artist_latitude', 'artist_longitude']]
    artist_df.columns = ['artist_id', 'name', 'location', 'latitude', 'longitude']
    bulk_song_df_dict['artists'] = bulk_song_df_dict['artists'].append(artist_df, sort=False)


def process_log_file(cur, filepath):
    # open log file
    df = pd.read_json(filepath, lines=True)

    # filter by NextSong action
    df = df[df['page'] == 'NextSong']

    # convert timestamp column to datetime
    t = pd.to_datetime(df['ts'], unit='ms')

    # append time data records
    time_data = [(dt, dt.hour, dt.day, dt.week, dt.month, dt.year, dt.day_name()) for dt in t]
    column_labels = ('start_time', 'hour', 'day', 'week', 'month', 'year', 'weekday')
    time_df = pd.DataFrame(time_data, columns=column_labels)
    bulk_log_df_dict['time'] = bulk_log_df_dict['time'].append(time_df)

    # append user records
    user_df = df[['userId', 'firstName', 'lastName', 'gender', 'level']]
    user_df = user_df[user_df['userId'].astype(bool)]
    user_df['userId'] = df['userId'].astype(str)
    user_df = user_df.drop_duplicates(subset='userId')
    user_df.columns = ['user_id', 'first_name', 'last_name', 'gender', 'level']
    bulk_log_df_dict['users'] = bulk_log_df_dict['users'].append(user_df)

    # insert songplay records
    rows_list = []
    for index, row in df.iterrows():
        # get song_id and artist_id from song and artist tables
        cur.execute(song_select, (row.song, row.artist, int(round(row.length))))
        result = cur.fetchone()
        (song_id, artist_id) = (result if result else (None, None))

        # uncomment if we only want records with valid song_id and artist_id
        # if song_id is None or artist_id is None:
        #     continue

        rows_list.append({
            'start_time': pd.to_datetime(round(row.ts / 1000.0)),
            'user_id': row.userId,
            'level': row.level,
            'song_id': song_id,
            'artist_id': artist_id,
            'session_id': row.sessionId,
            'location': row.location,
            'user_agent': row.userAgent
        })

    songplay_df = pd.DataFrame(rows_list)
    bulk_log_df_dict['songplays'] = bulk_log_df_dict['songplays'].append(songplay_df)


def process_data(cur, filepath, func):
    # get all files matching extension from directory
    all_files = []
    for root, dirs, files in os.walk(filepath):
        files = glob.glob(os.path.join(root, '*.json'))
        for f in files:
            all_files.append(os.path.abspath(f))

    # get total number of files found
    num_files = len(all_files)
    print('{} files found in {}'.format(num_files, filepath))

    # iterate over files and process
    for i, datafile in enumerate(all_files, 1):
        func(cur, datafile)
        print('{}/{} files processed.'.format(i, num_files))


def copy_dataframe_to_db(cur, df, table):
    sio = io.StringIO()
    sio.write(df.to_csv(index=None, header=None, na_rep='NULL', sep='|'))  # Write the DataFrame as a csv to the buffer
    sio.seek(0)  # Be sure to reset the position to the start of the stream
    # print(sio.getvalue())
    cur.copy_from(sio, table, columns=df.columns, sep='|', null='NULL')


def copy_dataframes_to_db(conn, cur, df_dict):
    for table, df in df_dict.items():
        df.replace('', 'NULL', inplace=True)
        copy_dataframe_to_db(cur, df, table)
        conn.commit()


def main():
    global bulk_df_dict

    conn = psycopg2.connect("host=127.0.0.1 dbname=sparkifydb user=student password=student")
    cur = conn.cursor()

    process_data(cur, filepath='../data/song_data', func=process_song_file)
    bulk_song_df_dict['artists'].drop_duplicates(subset='artist_id', keep='first', inplace=True)
    copy_dataframes_to_db(conn, cur, bulk_song_df_dict)

    process_data(cur, filepath='../data/log_data', func=process_log_file)
    bulk_log_df_dict['users'].drop_duplicates(subset='user_id', keep='first', inplace=True)
    bulk_log_df_dict['time'].drop_duplicates(subset='start_time', keep='first', inplace=True)
    copy_dataframes_to_db(conn, cur, bulk_log_df_dict)


    conn.close()


if __name__ == "__main__":
    main()
