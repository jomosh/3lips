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
      // Schedule the next fetch after a delay (2 seconds —
      // ADS-B position data from tar1090 updates every ~1-2 s per
      // aircraft, so 2 s polling is sufficient and halves the
      // pressure on the API proxy rate limiter.)
      setTimeout(event_adsb, 2000);
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
  let alt_baro_ft = aircraftData.alt_baro; // dump1090/tar1090 reports baro altitude in FEET
  const seen_pos = aircraftData.seen_pos;

  // Check if the aircraft has valid position data
  if (lat !== undefined && lon !== undefined && alt_baro_ft !== undefined && seen_pos < 10) {
    // Guard against non-numeric alt_baro (tar1090 can emit "ground" as a string)
    if (typeof alt_baro_ft !== 'number' || isNaN(alt_baro_ft)) {
      alt_baro_ft = 0;
    }
    // Convert feet → metres for internal colour mapping and display
    var alt_m = alt_baro_ft * 0.3048;
    var color = getAltitudeColor(alt_m);
    addPoint(lat, lon, alt_m, flight || hex, color, 10, "adsb", Date.now());

    // Build label text: callsign on top line, formatted altitude on second line
    var namePart;
    if (flight && flight.trim() !== '') {
      namePart = sanitizeLabel(flight.trim());
    } else {
      namePart = hex;
    }
    var labelText = namePart + '\n' + formatAltitude(alt_m);
    updateTargetLabel("adsb", hex, lat, lon, labelText, color);
  }
}