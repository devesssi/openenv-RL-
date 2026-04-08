const express = require('express');
const router = express.Router();

// BUG 2 (Medium): There is a syntax error below.
// The closing parenthesis for router.get() is missing,
// which will cause Node.js to crash on startup with a SyntaxError.

const users = [
  { id: 1, name: 'Alice', email: 'alice@example.com' },
  { id: 2, name: 'Bob', email: 'bob@example.com' },
  { id: 3, name: 'Charlie', email: 'charlie@example.com' }
];

router.get('/', (req, res) => {
  res.json({ users: users });
};

module.exports = router;
