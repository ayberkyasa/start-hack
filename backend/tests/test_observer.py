import unittest

from app.target.observer import LibraryObserver, Observer, ReadError, ReadFailure
from app.target.replay import LibraryReplay


class ObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_follow_cursor_and_preserve_history(self):
        playback = LibraryReplay()
        reader: Observer = LibraryObserver(playback)
        self.assertEqual(await reader.sessions(), ())
        self.assertEqual((await reader.scenarios())[0].id, "library")
        self.assertEqual(await reader.channels(), playback.channels())
        with self.assertRaises(ReadError) as error:
            await reader.history("unknown")
        self.assertEqual(error.exception.kind, ReadFailure.NOT_FOUND)
        playback.advance("open")
        self.assertEqual((await reader.session("session-1")).touches_used, 0)
        for step in playback.steps()[1:]:
            playback.advance(step)
        observed = await reader.history("session-1")
        self.assertEqual(len(observed.events), 5)
        self.assertEqual(observed, await reader.history("session-1"))
        session, = await reader.sessions()
        self.assertEqual(session.status, "ended")
        self.assertEqual(session.touches_used, 3)
