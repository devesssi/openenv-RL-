const express = require('express');
const router = express.Router();

// Simulates fetching data from a database
function fetchDataFromDB() {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        records: [
          { id: 1, value: 'sensor_alpha', reading: 42.5 },
          { id: 2, value: 'sensor_beta', reading: 17.3 },
          { id: 3, value: 'sensor_gamma', reading: 88.1 }
        ],
        timestamp: new Date().toISOString()
      });
    }, 100);
  });
}

// BUG 3 (Hard): The handler is marked async but does NOT await the Promise.
// This means `result` will be a pending Promise object, not the resolved data.
// Express will try to serialize the Promise, resulting in an empty/broken response
// or a 500 error when the client expects valid JSON.

router.get('/', async (req, res) => {
  try {
    const result = fetchDataFromDB();
    if (!result || !result.records) {
      return res.status(500).json({ error: 'Failed to fetch data' });
    }
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
