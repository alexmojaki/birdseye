var gulp = require('gulp'),
    eslint = require('gulp-eslint');

gulp.task('lint', function() {
    return gulp.src('../birdseye/static/js/call.js')
    .pipe(eslint('.eslintrc.json'))
    .pipe(eslint.format())
});

gulp.task('default', function () {
    return gulp.watch(['../birdseye/static/js/call.js'], ['lint']);
});
