import random
import unittest
from mini_dbms.bptree import BPlusTree

class BPlusTreeTests(unittest.TestCase):
    def test_empty_first_insert_duplicate(self):
        tree = BPlusTree(max_keys=3)
        self.assertIsNone(tree.get(9))
        tree.insert(9, 90)
        self.assertEqual(tree.get(9), 90)
        with self.assertRaises(ValueError): tree.insert(9, 91)
    def test_leaf_internal_root_splits_and_link_order(self):
        tree = BPlusTree(max_keys=3)
        for key in range(80): tree.insert(key, key * 10)
        self.assertGreaterEqual(len(tree.root.children), 2)
        self.assertEqual(list(tree.items()), [(key, key * 10) for key in range(80)])
        for key in range(80): self.assertEqual(tree.get(key), key * 10)
        self.assertIsNone(tree.get(100))
        self.assertGreater(tree.last_visits, 1)
    def test_random_insertion_and_leaf_chain(self):
        keys = list(range(300)); random.Random(4421).shuffle(keys)
        tree = BPlusTree(max_keys=5)
        for key in keys: tree.insert(key, -key)
        self.assertEqual([key for key, _ in tree.items()], list(range(300)))
        self.assertTrue(all(tree.get(k) == -k for k in range(300)))
    def test_sql_index_equals_independent_scan(self):
        import tempfile
        from mini_dbms import Database
        with tempfile.TemporaryDirectory() as directory:
            db = Database(directory, tree_max_keys=3)
            expected = {}
            keys = list(range(100)); random.Random(71).shuffle(keys)
            for value in keys:
                inserted_id = db.execute(f"INSERT INTO players (display_name, created_at) VALUES ('p{value}', 'day')")["insertedId"]
                expected[inserted_id] = f"p{value}"
            for row_id, name in expected.items():
                indexed = db.execute(f"SELECT display_name FROM players WHERE id = {row_id}")["rows"]
                scanned = [row[0]["display_name"] for row in db.tables["players"].rows if row[0]["id"] == row_id]
                self.assertEqual(indexed, [{"display_name": name}])
                self.assertEqual([item["display_name"] for item in indexed], scanned)
            self.assertEqual(db.execute("SELECT display_name FROM players WHERE display_name = 'p17'")["rows"], [{"display_name": "p17"}])

if __name__ == "__main__": unittest.main()
