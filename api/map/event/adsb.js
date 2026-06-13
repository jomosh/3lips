function event_adsb() {

  fetch(adsb_url)
    .then(response => {
      if (!response.ok) {
        throw new Error('Network response was not ok');
      }
      return response.json();
    })
    .then(data => {
      // Update aircraft points based on new data
      updateAircraftPoints(data);
    })
    .catch(error => {
      // Handle errors during fetch
      console.error('Error during fetch:', error);
    })
    .finally(() => {
      // Schedule the next fetch after a delay (e.g., 1 second)
      setTimeout(event_adsb, 1000);
    });
}

// Function to update aircraft points
function updateAircraftPoints(data) {

  removeEntitiesOlderThanAndFade("adsb", 60, 0.5);

  // Build a set of hex codes seen this poll so we can prune stale labels
  var seenHex = {};

  // Process aircraft data and add points
  const aircraft = data.aircraft || [];
  aircraft.forEach(function(ac) {
    processAircraftData(ac);
    if (ac.hex) seenHex[ac.hex] = true;
  });

  // Remove labels for aircraft that have disappeared
  for (var id in _targetLabelFeatures) {
    if (_targetLabelFeatures.hasOwnProperty(id) && id.indexOf('adsb_') === 0) {
      var hex = id.substring(5); // strip "adsb_"
      if (!seenHex[hex]) {
        removeTargetLabel("adsb", hex);
      }
    }
  }
}

// Function to process aircraft data
function processAircraftData(aircraftData) {
  const hex = aircraftData.hex;
  const flight = aircraftData.flight;
  const lat = aircraftData.lat;
  const lon = aircraftData.lon;
  const alt = aircraftData.alt_baro;
  const seen_pos = aircraftData.seen_pos;

  // Check if the aircraft has valid position data
  if (lat !== undefined && lon !== undefined && alt !== undefined && seen_pos < 10) {
    var color = getAltitudeColor(alt);
    addPoint(lat, lon, alt, flight || hex, color, 10, "adsb", Date.now());

    // Build label text: "CALLSIGN · ALTm" or "· ALTm" if no callsign
    var labelText;
    if (flight && flight.trim() !== '') {
      labelText = flight.trim() + ' · ' + Math.round(alt) + 'm';
    } else {
      labelText = hex + ' · ' + Math.round(alt) + 'm';
    }
    updateTargetLabel("adsb", hex, lat, lon, labelText, color);
  }
}