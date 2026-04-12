const express = require('express');
const router = express.Router();

const users = [
  { id: 1, name: 'Alice', email: 'alice@example.com', role: 'admin' },
  { id: 2, name: 'Bob', email: 'bob@example.com', role: 'user' },
  { id: 3, name: 'Charlie', email: 'charlie@example.com', role: 'user' },
  { id: 4, name: 'Diana', email: 'diana@example.com', role: 'moderator' }
];

router.get('/', (req, res) => {
  const role = req.query.role;
  if (role) {
    const filtered = users.filter(u => u.role === role);
    return res.json({ users: filtered, count: filtered.length });
  }
  res.json({ users: users, count: users.length });
};

module.exports = router;
