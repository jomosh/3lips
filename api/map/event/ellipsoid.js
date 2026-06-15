function event_ellipsoid() {

  var radar_url = window.location.origin +
    '/api' + window.location.search;

  fetch(radar_url)
    .then(response => {
      if (!response.ok) {
        throw new Error('Network response was not ok');
      }
      return response.json();
    })
    .then(data => {

      if (!data["ellipsoids"]) {
        return;
      }

      // Client-side filtering: only show ellipsoids when the number of
      // radars with ellipsoid data meets or exceeds the user-configured
      // threshold (default 3, stored in window.minRadarEllipsoids).
      var ellipsoidCount = Object.keys(data["ellipsoids"]).length;
      var threshold = (typeof window.minRadarEllipsoids !== 'undefined')
        ? window.minRadarEllipsoids : 3;
      if (ellipsoidCount < threshold) {
        removeEntitiesByType("ellipsoids");
        return;
      }

      if (Object.keys(data["ellipsoids"]).length !== 0) {
        removeEntitiesByType("ellipsoids");
      }
      else {
        removeEntitiesOlderThanAndFade("ellipsoids", 10, 0.5);
      }
      for (const key in data["ellipsoids"]) {
        if (data["ellipsoids"].hasOwnProperty(key)) {
          const points = data["ellipsoids"][key];

          for (const point in points) {
            addPoint(
              points[point][0],
              points[point][1],
              points[point][2],
              "ellipsoids",
              style_ellipsoid.color,
              style_ellipsoid.pointSize,
              style_ellipsoid.type,
              Date.now()
            );
          }

        }
      }
    })
    .catch(error => {
      // Handle errors during fetch
      console.error('Error during fetch:', error);
    })
    .finally(() => {
      // Schedule the next fetch after a delay (e.g., 5 seconds)
      setTimeout(event_ellipsoid, 1000);
    });

}

// Ellipsoid style uses a bright magenta colour (hue 300°)
// which is intentionally outside the altitude colour palette
// (orange 30° → purple 280°) so ellipsoid points are never
// confused with altitude-mapped detections.
var style_ellipsoid = {};
style_ellipsoid.color = 'rgba(255, 0, 255, 0.45)';
style_ellipsoid.pointSize = 16;
style_ellipsoid.type = "ellipsoids";
style_ellipsoid.timestamp = Date.now();