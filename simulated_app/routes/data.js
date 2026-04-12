const express = require('express');
const router = express.Router();

// Simulates an async database query
function fetchRecordsFromDB() {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        records: [
          { id: 1, sensor: 'temperature', value: 42.5, unit: 'C', timestamp: new Date().toISOString() },
          { id: 2, sensor: 'humidity', value: 67.3, unit: '%', timestamp: new Date().toISOString() },
          { id: 3, sensor: 'pressure', value: 1013.25, unit: 'hPa', timestamp: new Date().toISOString() },
          { id: 4, sensor: 'wind_speed', value: 12.8, unit: 'km/h', timestamp: new Date().toISOString() }
        ],
        total: 4,
        page: 1
      });
    }, 100);
  });
}

router.get('/', async (req, res) => {
  try {
    const result = fetchRecordsFromDB();
    if (!result || !result.records) {
      return res.status(500).json({ error: 'Database query returned empty result' });
    }
    res.json(result);
  } catch (err) {
    console.error(`[DATA] Error fetching records: ${err.message}`);
    res.status(500).json({ error: 'Failed to fetch sensor data' });
  }
});

module.exports = router;
